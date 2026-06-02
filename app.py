import os
import re
from datetime import datetime
from flask import Flask, request, send_from_directory, jsonify, render_template
from flask_cors import CORS
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv

load_dotenv()

import database as db
import categorizer
import advisor
import intent_parser
import voice
import scheduler
from translations import t

app = Flask(__name__)
CORS(app)

CURRENCY = os.getenv("CURRENCY", "R$")


def fmt(amount):
    return f"{CURRENCY} {amount:,.2f}"


def check_budget_alerts(phone, category, lang):
    budgets = {row["category"]: row["limit_amount"] for row in db.get_budgets(phone)}
    if category not in budgets:
        return None
    spent = db.get_category_spending_this_month(phone, category)
    limit = budgets[category]
    pct = (spent / limit) * 100
    if pct >= 100:
        return t(lang, "budget_exceeded", category=category, spent=fmt(spent), limit=fmt(limit))
    elif pct >= 80:
        return t(lang, "budget_warning", category=category, pct=pct, spent=fmt(spent), limit=fmt(limit))
    return None


def handle_balance(phone, lang):
    rows = db.get_monthly_summary(phone)
    if not rows:
        return t(lang, "no_transactions")

    now = datetime.now()
    expenses, incomes = {}, {}
    for row in rows:
        if row["type"] == "expense":
            expenses[row["category"]] = row["total"]
        else:
            incomes[row["category"]] = row["total"]

    total_exp = sum(expenses.values())
    total_inc = sum(incomes.values())
    net = total_inc - total_exp

    lines = [t(lang, "summary_title", month=now.strftime("%B %Y")) + "\n"]

    if incomes:
        lines.append(t(lang, "income_header"))
        for cat, amt in incomes.items():
            lines.append(f"  • {cat}: {fmt(amt)}")
        lines.append("  " + t(lang, "total", amount=fmt(total_inc)) + "\n")

    if expenses:
        lines.append(t(lang, "expense_header"))
        budgets = {r["category"]: r["limit_amount"] for r in db.get_budgets(phone)}
        for cat, amt in sorted(expenses.items(), key=lambda x: -x[1]):
            budget_info = ""
            if cat in budgets:
                pct = (amt / budgets[cat]) * 100
                bar = "🔴" if pct >= 100 else "🟡" if pct >= 80 else "🟢"
                budget_info = f" {bar} {pct:.0f}%"
            lines.append(f"  • {cat}: {fmt(amt)}{budget_info}")
        lines.append("  " + t(lang, "total", amount=fmt(total_exp)) + "\n")

    emoji = "✅" if net >= 0 else "❌"
    lines.append(t(lang, "net", emoji=emoji, amount=fmt(net)))
    return "\n".join(lines)


def handle_last(phone, lang):
    rows = db.get_recent_transactions(phone)
    if not rows:
        return t(lang, "no_recent")
    lines = [t(lang, "recent_title") + "\n"]
    for row in rows:
        icon = "💚" if row["type"] == "income" else "🔴"
        desc = row["description"] or row["category"]
        lines.append(f"{icon} {fmt(row['amount'])} – {desc} [{row['category']}] [{row['created_at'][:10]}]")
    return "\n".join(lines)


def handle_budgets(phone, lang):
    rows = db.get_budgets(phone)
    if not rows:
        return t(lang, "no_budgets")
    lines = [t(lang, "budgets_title") + "\n"]
    for row in rows:
        spent = db.get_category_spending_this_month(phone, row["category"])
        pct = (spent / row["limit_amount"]) * 100
        bar = "🔴" if pct >= 100 else "🟡" if pct >= 80 else "🟢"
        lines.append(f"{bar} *{row['category']}:* {fmt(spent)} / {fmt(row['limit_amount'])} ({pct:.0f}%)")
    return "\n".join(lines)


def handle_message(phone, body):
    text = body.strip()
    lang = db.get_language(phone)

    # Load conversation context for follow-up understanding
    last_msg, last_reply = db.get_last_context(phone)

    # Parse intent using Claude Haiku with conversation context
    parsed = intent_parser.parse_intent(text, last_message=last_msg, last_reply=last_reply)
    intent = parsed.get("intent", "unknown")

    # Auto-update language if detected
    detected_lang = parsed.get("lang")
    if detected_lang and detected_lang in ("en", "pt", "es") and detected_lang != lang:
        lang = detected_lang
        db.set_language(phone, lang)

    # Track usage for personalization
    db.log_usage(phone, intent)

    if intent == "help":
        return t(lang, "help")

    if intent == "balance":
        return handle_balance(phone, lang)

    if intent == "last":
        return handle_last(phone, lang)

    if intent == "undo":
        if db.delete_last_transaction(phone):
            return t(lang, "undo_ok")
        return t(lang, "undo_none")

    if intent == "budgets":
        return handle_budgets(phone, lang)

    if intent == "set_budget":
        category = parsed.get("category", "Other")
        limit = parsed.get("limit")
        if not limit:
            return t(lang, "budget_invalid")
        db.set_budget(phone, category, float(limit))
        return t(lang, "budget_set", category=category, amount=fmt(float(limit)))

    if intent == "set_language":
        new_lang = detected_lang or lang
        db.set_language(phone, new_lang)
        return t(new_lang, "language_set")

    if intent == "chat":
        try:
            return advisor.ask_advisor(phone, text, CURRENCY, lang, is_chat=True)
        except Exception as e:
            return t(lang, "ai_error", error=str(e))

    if intent == "general":
        try:
            return advisor.ask_general(text, lang)
        except Exception as e:
            return t(lang, "ai_error", error=str(e))

    if intent == "set_reminder":
        remind_text = parsed.get("remind_text", "")
        remind_at = parsed.get("remind_at", "")
        if not remind_text or not remind_at:
            return "❌ I didn't catch the reminder details. Try: 'remind me to call mom at 5pm'"
        db.add_reminder(phone, remind_text, remind_at)
        if lang == "pt":
            return f"⏰ Lembrete definido! Vou te avisar: *{remind_text}* em {remind_at[11:16]} 👍"
        elif lang == "es":
            return f"⏰ ¡Recordatorio creado! Te aviso: *{remind_text}* a las {remind_at[11:16]} 👍"
        else:
            return f"⏰ Got it! I'll remind you to *{remind_text}* at {remind_at[11:16]} 👍"

    if intent == "list_reminders":
        rows = db.get_pending_reminders(phone)
        if not rows:
            if lang == "pt":
                return "📭 Nenhum lembrete pendente."
            elif lang == "es":
                return "📭 Sin recordatorios pendientes."
            else:
                return "📭 No pending reminders."
        lines = ["⏰ *Your reminders:*\n"] if lang == "en" else ["⏰ *Seus lembretes:*\n"] if lang == "pt" else ["⏰ *Tus recordatorios:*\n"]
        for row in rows:
            lines.append(f"• {row['remind_at'][11:16]} — {row['text']}")
        return "\n".join(lines)

    if intent == "delete_reminder":
        rows = db.get_pending_reminders(phone)
        if rows:
            db.delete_reminder(phone, rows[-1]["id"])
            return "✅ Last reminder deleted." if lang == "en" else "✅ Último lembrete apagado." if lang == "pt" else "✅ Último recordatorio eliminado."
        return "❌ No reminders to delete."

    # ── Calendar ────────────────────────────────────────────────
    if intent == "add_event":
        title = parsed.get("title", "")
        event_at = parsed.get("event_at", "")
        remind_before = parsed.get("remind_before", 60)
        if not title or not event_at:
            return "❌ I need a title and time. Example: 'add event dentist appointment tomorrow at 2pm'"
        db.add_event(phone, title, event_at, remind_before=remind_before)
        time_str = event_at[11:16] if len(event_at) > 10 else event_at
        date_str = event_at[:10]
        if lang == "pt":
            return f"📅 Evento adicionado: *{title}*\n📆 {date_str} às {time_str}\n⏰ Lembrete {remind_before} min antes"
        elif lang == "es":
            return f"📅 Evento agregado: *{title}*\n📆 {date_str} a las {time_str}\n⏰ Recordatorio {remind_before} min antes"
        return f"📅 Event added: *{title}*\n📆 {date_str} at {time_str}\n⏰ Reminder {remind_before} min before"

    if intent == "list_events":
        events = db.get_upcoming_events(phone, days=14)
        reminders = db.get_pending_reminders(phone)
        lines = []
        if events:
            lines.append("📅 *Upcoming events:*" if lang == "en" else "📅 *Próximos eventos:*")
            for e in events:
                lines.append(f"• {e['event_at'][:10]} {e['event_at'][11:16]} — *{e['title']}*")
        if reminders:
            lines.append("\n⏰ *Reminders:*" if lang == "en" else "\n⏰ *Lembretes:*")
            for r in reminders:
                lines.append(f"• {r['remind_at'][11:16]} — {r['text']}")
        if not lines:
            return "📭 Nothing scheduled." if lang == "en" else "📭 Nada agendado." if lang == "pt" else "📭 Nada programado."
        return "\n".join(lines)

    # ── Recurring Transactions ──────────────────────────────────
    if intent == "add_recurring":
        amount = parsed.get("amount")
        description = parsed.get("description", "")
        tx_type = parsed.get("type", "expense")
        day = parsed.get("day_of_month", 1)
        if not amount:
            return "❌ I need an amount. Example: 'recurring expense 100 netflix on the 15th'"
        category = categorizer.categorize(description) if tx_type == "expense" else "Income"
        db.add_recurring(phone, float(amount), category, description, tx_type, int(day))
        if lang == "pt":
            return f"🔄 Transação recorrente criada!\n*{description}* — {fmt(float(amount))} todo dia {day}"
        return f"🔄 Recurring transaction set!\n*{description}* — {fmt(float(amount))} every {day}{'st' if day==1 else 'nd' if day==2 else 'rd' if day==3 else 'th'}"

    if intent == "list_recurring":
        rows = db.get_recurring(phone)
        if not rows:
            return "No recurring transactions set." if lang == "en" else "Nenhuma transação recorrente."
        lines = ["🔄 *Recurring transactions:*\n"]
        for r in rows:
            icon = "💚" if r["type"] == "income" else "🔴"
            lines.append(f"{icon} {fmt(r['amount'])} — {r['description']} (day {r['day_of_month']})")
        return "\n".join(lines)

    # ── Savings Goals ───────────────────────────────────────────
    if intent == "add_goal":
        name = parsed.get("name", "")
        target = parsed.get("target_amount")
        deadline = parsed.get("deadline")
        if not name or not target:
            return "❌ Example: 'savings goal: trip to Europe, R$5000 by December'"
        db.add_savings_goal(phone, name, float(target), deadline)
        if lang == "pt":
            return f"🎯 Meta criada: *{name}*\nObjetivo: {fmt(float(target))}{f' | Prazo: {deadline}' if deadline else ''}"
        return f"🎯 Goal created: *{name}*\nTarget: {fmt(float(target))}{f' | Deadline: {deadline}' if deadline else ''}"

    if intent == "view_goals":
        goals = db.get_savings_goals(phone)
        if not goals:
            return "No savings goals yet. Try: 'savings goal trip R$5000'" if lang == "en" else "Nenhuma meta ainda."
        lines = ["🎯 *Savings Goals:*\n"] if lang == "en" else ["🎯 *Metas de Poupança:*\n"]
        for g in goals:
            pct = (g["saved_amount"] / g["target_amount"] * 100) if g["target_amount"] > 0 else 0
            bar = "🟢" if pct >= 100 else "🟡" if pct >= 50 else "🔴"
            lines.append(f"{bar} *{g['name']}*: {fmt(g['saved_amount'])} / {fmt(g['target_amount'])} ({pct:.0f}%)")
        return "\n".join(lines)

    if intent == "add_to_goal":
        goal_name = parsed.get("goal_name", "")
        amount = parsed.get("amount")
        if not goal_name or not amount:
            return "❌ Example: 'add 200 to trip goal'"
        db.add_to_goal(phone, goal_name, float(amount))
        if lang == "pt":
            return f"🎯 {fmt(float(amount))} adicionado à meta *{goal_name}*!"
        return f"🎯 {fmt(float(amount))} added to *{goal_name}* goal!"

    # ── To-Do List ──────────────────────────────────────────────
    if intent == "add_todo":
        todo_text = parsed.get("todo_text", text)
        db.add_todo(phone, todo_text)
        return f"✅ Added to your to-do list: *{todo_text}*" if lang == "en" else f"✅ Adicionado: *{todo_text}*" if lang == "pt" else f"✅ Agregado: *{todo_text}*"

    if intent == "list_todos":
        todos = db.get_todos(phone)
        reminders = db.get_pending_reminders(phone)
        events = db.get_upcoming_events(phone, days=1)
        lines = []
        if todos:
            lines.append("📋 *To-do:*" if lang == "en" else "📋 *Tarefas:*")
            for i, todo in enumerate(todos, 1):
                lines.append(f"{i}. {todo['text']}")
        if events:
            lines.append("\n📅 *Today's events:*" if lang == "en" else "\n📅 *Eventos hoje:*")
            for e in events:
                lines.append(f"• {e['event_at'][11:16]} — *{e['title']}*")
        if reminders:
            lines.append("\n⏰ *Reminders:*" if lang == "en" else "\n⏰ *Lembretes:*")
            for r in reminders:
                lines.append(f"• {r['remind_at'][11:16]} — {r['text']}")
        if not lines:
            return "📭 Nothing on your list today!" if lang == "en" else "📭 Nada na sua lista hoje!" if lang == "pt" else "📭 ¡Nada en tu lista hoy!"
        return "\n".join(lines)

    if intent == "complete_todo":
        todo_text = parsed.get("todo_text", "")
        db.complete_todo(phone, text_match=todo_text if todo_text else None)
        return "✅ Task marked as done!" if lang == "en" else "✅ Tarefa concluída!" if lang == "pt" else "✅ ¡Tarea completada!"

    # ── Notes & Memory ──────────────────────────────────────────
    if intent == "add_note":
        note_title = parsed.get("note_title", "Note")
        note_content = parsed.get("note_content", text)
        db.add_note(phone, note_title, note_content)
        return f"📝 Note saved: *{note_title}*" if lang == "en" else f"📝 Nota salva: *{note_title}*" if lang == "pt" else f"📝 Nota guardada: *{note_title}*"

    if intent == "list_notes":
        notes = db.get_notes(phone)
        if not notes:
            return "📭 No notes saved." if lang == "en" else "📭 Nenhuma nota salva." if lang == "pt" else "📭 Sin notas guardadas."
        lines = ["📝 *Your notes:*\n"] if lang == "en" else ["📝 *Suas notas:*\n"] if lang == "pt" else ["📝 *Tus notas:*\n"]
        for n in notes[:10]:
            lines.append(f"• *{n['title']}* — {n['content'][:50]}...")
        return "\n".join(lines)

    if intent == "search_note":
        query = parsed.get("query", text)
        results = db.search_notes(phone, query)
        if not results:
            return f"📭 No notes found for '{query}'"
        lines = [f"📝 *Found {len(results)} note(s):*\n"]
        for n in results:
            lines.append(f"• *{n['title']}*\n  {n['content']}")
        return "\n".join(lines)

    # ── Contacts & Birthdays ────────────────────────────────────
    if intent == "add_contact":
        name = parsed.get("name", "")
        birthday = parsed.get("birthday")  # MM-DD
        relationship = parsed.get("relationship", "")
        if not name:
            return "❌ Example: 'add contact: Jean, birthday 03-15, my brother'"
        db.add_contact(phone, name, birthday, relationship)
        bday_str = f" 🎂 {birthday}" if birthday else ""
        return f"👤 Contact saved: *{name}*{bday_str}" if lang == "en" else f"👤 Contato salvo: *{name}*{bday_str}" if lang == "pt" else f"👤 Contacto guardado: *{name}*{bday_str}"

    if intent == "list_contacts":
        contacts = db.get_contacts(phone)
        if not contacts:
            return "📭 No contacts saved." if lang == "en" else "📭 Nenhum contato salvo."
        lines = ["👥 *Contacts:*\n"] if lang == "en" else ["👥 *Contatos:*\n"] if lang == "pt" else ["👥 *Contactos:*\n"]
        for c in contacts:
            bday = f" 🎂 {c['birthday']}" if c["birthday"] else ""
            lines.append(f"• *{c['name']}*{bday} {c['relationship'] or ''}")
        return "\n".join(lines)

    # ── Morning Briefing ────────────────────────────────────────
    if intent == "set_briefing":
        btime = parsed.get("briefing_time", "08:00")
        db.update_settings(phone, briefing_time=btime, briefing_enabled=1)
        if lang == "pt":
            return f"☀️ Briefing matinal ativado para as *{btime}* todos os dias!"
        elif lang == "es":
            return f"☀️ ¡Briefing matinal activado a las *{btime}* todos los días!"
        return f"☀️ Morning briefing set for *{btime}* every day!"

    if intent == "toggle_briefing":
        enabled = parsed.get("enabled", True)
        db.update_settings(phone, briefing_enabled=1 if enabled else 0)
        if enabled:
            return "☀️ Morning briefing turned ON!" if lang == "en" else "☀️ Briefing matinal ativado!" if lang == "pt" else "☀️ ¡Briefing matinal activado!"
        return "🌙 Morning briefing turned OFF." if lang == "en" else "🌙 Briefing matinal desativado." if lang == "pt" else "🌙 Briefing matinal desactivado."

    if intent == "set_report":
        freq = parsed.get("frequency", "weekly")
        db.update_settings(phone, report_frequency=freq)
        return f"📊 Automatic {freq} reports enabled!" if lang == "en" else f"📊 Relatórios {freq} ativados!" if lang == "pt" else f"📊 ¡Reportes {freq} activados!"

    if intent == "advice":
        try:
            return "🤖 " + advisor.ask_advisor(phone, "Give me a full analysis of my spending and your top advice.", CURRENCY, lang)
        except Exception as e:
            return t(lang, "ai_error", error=str(e))

    if intent == "ai_question":
        question = parsed.get("question", text)
        try:
            return "🤖 " + advisor.ask_advisor(phone, question, CURRENCY, lang)
        except Exception as e:
            return t(lang, "ai_error", error=str(e))

    if intent == "log_expense":
        amount = parsed.get("amount")
        description = parsed.get("description", "expense")
        if not amount or float(amount) <= 0:
            return t(lang, "bad_amount")
        amount = float(amount)
        category = categorizer.categorize(description)
        db.add_transaction(phone, amount, category, description, "expense")
        response = t(lang, "expense_logged", amount=fmt(amount), desc=description, category=category)
        alert = check_budget_alerts(phone, category, lang)
        if alert:
            response += f"\n\n{alert}"
        return response

    if intent == "log_income":
        amount = parsed.get("amount")
        description = parsed.get("description", "income")
        if not amount or float(amount) <= 0:
            return t(lang, "bad_amount")
        amount = float(amount)
        db.add_transaction(phone, amount, "Income", description, "income")
        return t(lang, "income_logged", amount=fmt(amount), desc=description, category="Income")

    # Unknown intent — let Ava respond naturally instead of showing fallback
    try:
        return advisor.ask_advisor(phone, text, CURRENCY, lang, is_chat=True)
    except Exception:
        return t(lang, "fallback")


@app.route("/audio/<filename>")
def serve_audio(filename):
    return send_from_directory(voice.AUDIO_DIR, filename)


@app.route("/webhook", methods=["POST"])
def webhook():
    phone = request.form.get("From", "unknown")
    media_url = request.form.get("MediaUrl0", "")
    media_type = request.form.get("MediaContentType0", "")
    incoming = request.form.get("Body", "").strip()

    is_voice = "audio" in media_type and media_url
    resp = MessagingResponse()

    # Transcribe voice note if received
    if is_voice:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        lang_hint = db.get_language(phone)
        try:
            incoming = voice.transcribe_audio(media_url, account_sid, auth_token, lang=lang_hint)
        except Exception as e:
            resp.message(f"Sorry, I couldn't hear that clearly. Try again? ({e})")
            return str(resp), 200, {"Content-Type": "application/xml"}

    if not incoming:
        return str(resp), 200, {"Content-Type": "application/xml"}

    print(f"📩 FROM: {phone}")
    print(f"📩 MSG: {incoming}")
    reply = handle_message(phone, incoming)
    db.set_last_context(phone, incoming, reply)
    print(f"📤 REPLY: {reply[:200]}")
    parts = [p.strip() for p in reply.split("|||") if p.strip()]
    combined = " ".join(parts)

    # If user sent a voice note, reply with Ava's voice
    if is_voice:
        try:
            base_url = os.getenv("RAILWAY_STATIC_URL", "https://web-production-6f59e.up.railway.app")
            lang_hint = db.get_language(phone)
            audio_file = voice.synthesize_speech(combined, lang=lang_hint)
            audio_url = f"{base_url}/audio/{audio_file}"
            resp.message("").media(audio_url)
            print(f"🎙️ VOICE REPLY sent: {audio_url}")
            return str(resp), 200, {"Content-Type": "application/xml"}
        except Exception as e:
            print(f"❌ Voice reply failed: {e}")

    resp.message(combined)
    print(f"📤 SENDING: 1 combined message")

    return str(resp), 200, {"Content-Type": "application/xml"}


@app.route("/")
@app.route("/app")
def dashboard():
    return render_template("dashboard.html")


# ─── Voice Call Routes ───────────────────────────────────────
@app.route("/call/voice", methods=["GET", "POST"])
def call_voice():
    import call_handler
    return call_handler.twiml_greet(), 200, {"Content-Type": "application/xml"}


@app.route("/call/respond", methods=["POST"])
def call_respond():
    import call_handler
    return call_handler.twiml_respond(), 200, {"Content-Type": "application/xml"}


@app.route("/health")
def health():
    return {"status": "ok"}, 200


# ─── Mobile App API ──────────────────────────────────────────

@app.route("/api/v1/dashboard")
def api_dashboard():
    phone = db.get_primary_phone()
    if not phone:
        return jsonify({"status": "no_user", "message": "Start chatting with Ava on WhatsApp first!"})

    usage = db.get_usage_stats(phone)
    summary = db.get_monthly_summary(phone)
    recent = db.get_recent_transactions(phone, limit=10)
    budgets = db.get_budgets(phone)
    reminders = db.get_pending_reminders(phone)
    events = db.get_upcoming_events(phone, days=30)
    goals = db.get_savings_goals(phone)
    todos = db.get_todos(phone)
    lang = db.get_language(phone)
    now = datetime.now()

    expenses = {}
    income_total = 0
    for row in summary:
        if row["type"] == "expense":
            expenses[row["category"]] = row["total"]
        else:
            income_total += row["total"]
    total_exp = sum(expenses.values())

    # Determine widget order based on usage
    intent_scores = usage["by_intent"]
    finance_score = intent_scores.get("log_expense", 0) + intent_scores.get("log_income", 0) + intent_scores.get("balance", 0)
    reminder_score = intent_scores.get("set_reminder", 0) + intent_scores.get("list_reminders", 0)
    event_score = intent_scores.get("add_event", 0) + intent_scores.get("list_events", 0)
    goal_score = intent_scores.get("add_goal", 0) + intent_scores.get("view_goals", 0) + intent_scores.get("add_to_goal", 0)
    todo_score = intent_scores.get("add_todo", 0) + intent_scores.get("list_todos", 0)

    widget_scores = [
        ("finance", finance_score),
        ("reminders", reminder_score),
        ("events", event_score),
        ("goals", goal_score),
        ("todos", todo_score),
    ]
    widget_order = [w for w, s in sorted(widget_scores, key=lambda x: -x[1])]

    return jsonify({
        "status": "ok",
        "user": {
            "phone": phone,
            "lang": lang,
            "currency": CURRENCY,
            "days_active": usage["days_active"],
            "total_messages": usage["total_messages"],
            "is_personalized": usage["is_personalized"],
            "messages_to_personalize": max(0, 20 - usage["total_messages"]),
        },
        "finance": {
            "month": now.strftime("%B %Y"),
            "income": income_total,
            "expenses": total_exp,
            "net": income_total - total_exp,
            "by_category": [{"category": k, "amount": v} for k, v in sorted(expenses.items(), key=lambda x: -x[1])],
            "budgets": [{"category": r["category"], "limit": r["limit_amount"],
                         "spent": db.get_category_spending_this_month(phone, r["category"])} for r in budgets],
        },
        "reminders": [{"id": r["id"], "text": r["text"], "time": r["remind_at"]} for r in reminders[:10]],
        "events": [{"id": e["id"], "title": e["title"], "time": e["event_at"]} for e in events[:10]],
        "goals": [{"id": g["id"], "name": g["name"], "target": g["target_amount"],
                   "saved": g["saved_amount"], "deadline": g["deadline"]} for g in goals],
        "todos": [{"id": t["id"], "text": t["text"]} for t in todos[:20]],
        "recent_transactions": [{"type": r["type"], "amount": r["amount"],
                                  "description": r["description"], "category": r["category"],
                                  "date": r["created_at"][:10]} for r in recent],
        "widget_order": widget_order,
    })


if __name__ == "__main__":
    db.init_db()
    db.migrate_db()
    scheduler.start_scheduler()
    print("✅ Database initialized.")
    print("")
    print("╔══════════════════════════════════════════╗")
    print("║   ✨  AVA — Your AI Life Companion  ✨   ║")
    print("║      Personal Assistant on WhatsApp      ║")
    print("╚══════════════════════════════════════════╝")
    print("🚀 Running on http://localhost:5000")
    print("📲 Webhook: http://localhost:5000/webhook")
    app.run(debug=True, port=5000)

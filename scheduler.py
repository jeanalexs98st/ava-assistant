import os
import time
import threading
from datetime import datetime
import database as db

TWILIO_FROM = "whatsapp:+14155238886"
_twilio_client = None


def get_twilio():
    global _twilio_client
    if _twilio_client is None:
        from twilio.rest import Client
        _twilio_client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    return _twilio_client


def send(phone, message):
    try:
        get_twilio().messages.create(body=message, from_=TWILIO_FROM, to=phone)
    except Exception as e:
        print(f"❌ Send failed to {phone}: {e}")


def build_morning_briefing(phone):
    lang = db.get_language(phone)
    now = datetime.now()
    lines = []

    if lang == "pt":
        lines.append(f"☀️ *Bom dia! Aqui está seu resumo de hoje — {now.strftime('%d/%m/%Y')}*\n")
    elif lang == "es":
        lines.append(f"☀️ *¡Buenos días! Tu resumen de hoy — {now.strftime('%d/%m/%Y')}*\n")
    else:
        lines.append(f"☀️ *Good morning! Here's your daily briefing — {now.strftime('%B %d, %Y')}*\n")

    # Today's events
    events = db.get_upcoming_events(phone, days=1)
    if events:
        lines.append("📅 *Today's events:*" if lang == "en" else "📅 *Eventos de hoje:*" if lang == "pt" else "📅 *Eventos de hoy:*")
        for e in events:
            lines.append(f"  • {e['event_at'][11:16]} — {e['title']}")
        lines.append("")

    # Pending todos
    todos = db.get_todos(phone)
    if todos:
        lines.append("✅ *To-do:*" if lang == "en" else "✅ *Tarefas:*" if lang == "pt" else "✅ *Tareas:*")
        for t in todos[:5]:
            lines.append(f"  • {t['text']}")
        lines.append("")

    # Upcoming birthdays
    birthdays = db.get_upcoming_birthdays(phone, days=3)
    if birthdays:
        lines.append("🎂 *Upcoming birthdays:*" if lang == "en" else "🎂 *Aniversários próximos:*" if lang == "pt" else "🎂 *Cumpleaños próximos:*")
        for name, bday, rel in birthdays:
            days_left = (bday.date() - datetime.now().date()).days
            lines.append(f"  • {name} — {days_left} {'days' if lang == 'en' else 'dias' if lang == 'pt' else 'días'}")
        lines.append("")

    # Finance snapshot
    summary = db.get_monthly_summary(phone)
    if summary:
        expenses = sum(r["total"] for r in summary if r["type"] == "expense")
        income = sum(r["total"] for r in summary if r["type"] == "income")
        currency = os.getenv("CURRENCY", "R$")
        if lang == "pt":
            lines.append(f"💰 *Finanças do mês:* Receita {currency} {income:,.2f} | Gastos {currency} {expenses:,.2f}")
        elif lang == "es":
            lines.append(f"💰 *Finanzas del mes:* Ingresos {currency} {income:,.2f} | Gastos {currency} {expenses:,.2f}")
        else:
            lines.append(f"💰 *Month so far:* Income {currency} {income:,.2f} | Expenses {currency} {expenses:,.2f}")

    if lang == "pt":
        lines.append("\n_Tenha um ótimo dia! — Ava 👊_")
    elif lang == "es":
        lines.append("\n_¡Que tengas un gran día! — Ava 👊_")
    else:
        lines.append("\n_Have a great day! — Ava 👊_")

    return "\n".join(lines)


def build_weekly_report(phone):
    lang = db.get_language(phone)
    currency = os.getenv("CURRENCY", "R$")
    summary = db.get_monthly_summary(phone)
    if not summary:
        return None
    expenses = {r["category"]: r["total"] for r in summary if r["type"] == "expense"}
    income = sum(r["total"] for r in summary if r["type"] == "income")
    total_exp = sum(expenses.values())
    top = sorted(expenses.items(), key=lambda x: -x[1])[:3]

    if lang == "pt":
        lines = [f"📊 *Relatório Semanal — Ava*\n",
                 f"💚 Receita: {currency} {income:,.2f}",
                 f"🔴 Gastos: {currency} {total_exp:,.2f}",
                 f"{'✅' if income >= total_exp else '❌'} Saldo: {currency} {income - total_exp:,.2f}\n",
                 "*Maiores gastos:*"]
    elif lang == "es":
        lines = [f"📊 *Reporte Semanal — Ava*\n",
                 f"💚 Ingresos: {currency} {income:,.2f}",
                 f"🔴 Gastos: {currency} {total_exp:,.2f}",
                 f"{'✅' if income >= total_exp else '❌'} Neto: {currency} {income - total_exp:,.2f}\n",
                 "*Mayores gastos:*"]
    else:
        lines = [f"📊 *Weekly Report — Ava*\n",
                 f"💚 Income: {currency} {income:,.2f}",
                 f"🔴 Expenses: {currency} {total_exp:,.2f}",
                 f"{'✅' if income >= total_exp else '❌'} Net: {currency} {income - total_exp:,.2f}\n",
                 "*Top expenses:*"]

    for cat, amt in top:
        lines.append(f"  • {cat}: {currency} {amt:,.2f}")
    return "\n".join(lines)


def run_scheduler():
    last_briefing_date = {}
    last_report_week = {}

    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H:%M")

            # ── Due reminders ──────────────────────────────
            for row in db.get_due_reminders():
                lang = db.get_language(row["phone"])
                if lang == "pt":
                    msg = f"⏰ *Lembrete:* {row['text']}"
                elif lang == "es":
                    msg = f"⏰ *Recordatorio:* {row['text']}"
                else:
                    msg = f"⏰ *Reminder:* {row['text']}"
                send(row["phone"], msg)
                db.mark_reminder_sent(row["id"])

            # ── Due event reminders ────────────────────────
            for event in db.get_due_event_reminders():
                lang = db.get_language(event["phone"])
                event_time = event["event_at"][11:16]
                if lang == "pt":
                    msg = f"📅 *Lembrete de evento:* {event['title']} às {event_time}"
                elif lang == "es":
                    msg = f"📅 *Recordatorio:* {event['title']} a las {event_time}"
                else:
                    msg = f"📅 *Event reminder:* {event['title']} at {event_time}"
                send(event["phone"], msg)
                db.mark_event_reminder_sent(event["id"])

            # ── Recurring transactions ─────────────────────
            for rec in db.get_due_recurring():
                db.add_transaction(rec["phone"], rec["amount"], rec["category"], rec["description"], rec["type"])
                db.mark_recurring_logged(rec["id"])
                lang = db.get_language(rec["phone"])
                currency = os.getenv("CURRENCY", "R$")
                if rec["type"] == "income":
                    if lang == "pt":
                        msg = f"💚 *Receita recorrente registrada:* {currency} {rec['amount']:,.2f} — {rec['description']}"
                    else:
                        msg = f"💚 *Recurring income logged:* {currency} {rec['amount']:,.2f} — {rec['description']}"
                else:
                    if lang == "pt":
                        msg = f"🔄 *Despesa recorrente registrada:* {currency} {rec['amount']:,.2f} — {rec['description']}"
                    else:
                        msg = f"🔄 *Recurring expense logged:* {currency} {rec['amount']:,.2f} — {rec['description']}"
                send(rec["phone"], msg)

            # ── Birthday reminders ─────────────────────────
            with db.get_db() as conn:
                all_phones = conn.execute("SELECT DISTINCT phone FROM contacts").fetchall()
            for row in all_phones:
                phone = row["phone"]
                for name, bday, rel, days_left in db.get_due_birthday_reminders(phone):
                    lang = db.get_language(phone)
                    if days_left == 0:
                        msg = f"🎂 *Today is {name}'s birthday!* Don't forget to wish them well! 🎉"
                        if lang == "pt":
                            msg = f"🎂 *Hoje é aniversário de {name}!* Não esquece de dar os parabéns! 🎉"
                        elif lang == "es":
                            msg = f"🎂 *¡Hoy es el cumpleaños de {name}!* ¡No olvides felicitarle! 🎉"
                    else:
                        msg = f"🎂 *{name}'s birthday is in {days_left} days!*"
                        if lang == "pt":
                            msg = f"🎂 *Aniversário de {name} em {days_left} dias!*"
                        elif lang == "es":
                            msg = f"🎂 *¡El cumpleaños de {name} es en {days_left} días!*"
                    send(phone, msg)

            # ── Morning briefing ───────────────────────────
            with db.get_db() as conn:
                users = conn.execute(
                    "SELECT phone, briefing_time FROM user_settings WHERE briefing_enabled = 1"
                ).fetchall()
            for user in users:
                phone = user["phone"]
                briefing_time = user["briefing_time"] or "08:00"
                if time_str == briefing_time and last_briefing_date.get(phone) != today_str:
                    briefing = build_morning_briefing(phone)
                    send(phone, briefing)
                    last_briefing_date[phone] = today_str

            # ── Weekly reports ─────────────────────────────
            with db.get_db() as conn:
                weekly_users = conn.execute(
                    "SELECT phone FROM user_settings WHERE report_frequency = 'weekly'"
                ).fetchall()
            week_str = now.strftime("%Y-W%W")
            if now.weekday() == 0 and time_str == "09:00":  # Monday 9am
                for user in weekly_users:
                    phone = user["phone"]
                    if last_report_week.get(phone) != week_str:
                        report = build_weekly_report(phone)
                        if report:
                            send(phone, report)
                        last_report_week[phone] = week_str

        except Exception as e:
            print(f"❌ Scheduler error: {e}")

        time.sleep(30)


def start_scheduler():
    thread = threading.Thread(target=run_scheduler, daemon=True)
    thread.start()
    print("⏰ Scheduler started — reminders, events, briefings, recurring transactions active.")

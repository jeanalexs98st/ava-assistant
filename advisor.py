import os
import anthropic
import database as db
from datetime import datetime


def build_financial_context(phone, currency):
    now = datetime.now()
    month_name = now.strftime("%B %Y")

    summary_rows = db.get_monthly_summary(phone)
    recent_rows = db.get_recent_transactions(phone, limit=10)
    budget_rows = db.get_budgets(phone)

    expenses = {}
    incomes = {}
    for row in summary_rows:
        if row["type"] == "expense":
            expenses[row["category"]] = row["total"]
        else:
            incomes[row["category"]] = row["total"]

    total_income = sum(incomes.values())
    total_expenses = sum(expenses.values())
    net = total_income - total_expenses

    lines = [f"User's financial data for {month_name}:\n"]

    if incomes:
        lines.append("INCOME THIS MONTH:")
        for cat, amt in incomes.items():
            lines.append(f"  - {cat}: {currency} {amt:,.2f}")
        lines.append(f"  Total income: {currency} {total_income:,.2f}\n")
    else:
        lines.append("INCOME THIS MONTH: None recorded\n")

    if expenses:
        lines.append("EXPENSES THIS MONTH:")
        for cat, amt in sorted(expenses.items(), key=lambda x: -x[1]):
            lines.append(f"  - {cat}: {currency} {amt:,.2f}")
        lines.append(f"  Total expenses: {currency} {total_expenses:,.2f}\n")
    else:
        lines.append("EXPENSES THIS MONTH: None recorded\n")

    lines.append(f"NET BALANCE: {currency} {net:,.2f} ({'surplus' if net >= 0 else 'deficit'})\n")

    if budget_rows:
        lines.append("BUDGETS:")
        for row in budget_rows:
            spent = db.get_category_spending_this_month(phone, row["category"])
            pct = (spent / row["limit_amount"] * 100) if row["limit_amount"] > 0 else 0
            status = "EXCEEDED" if pct >= 100 else "WARNING" if pct >= 80 else "OK"
            lines.append(
                f"  - {row['category']}: {currency} {spent:,.2f} / {currency} {row['limit_amount']:,.2f} ({pct:.0f}%) [{status}]"
            )
        lines.append("")

    if recent_rows:
        lines.append("LAST 10 TRANSACTIONS:")
        for row in recent_rows:
            lines.append(
                f"  - {row['type'].upper()}: {currency} {row['amount']:,.2f} | {row['description']} [{row['category']}] on {row['created_at'][:10]}"
            )

    return "\n".join(lines)


LANG_NAMES = {"en": "English", "pt": "Portuguese (Brazilian)", "es": "Spanish"}


def ask_general(user_question, lang="en"):
    """Ava answers any general question as a personal assistant."""
    language_name = LANG_NAMES.get(lang, "English")
    system_prompt = f"""You are Ava — a smart, helpful personal assistant and close friend texting on WhatsApp.

You can help with ANYTHING: questions, advice, recipes, writing, ideas, planning, health tips, travel, relationships, work problems, general knowledge — whatever the person needs.

Your personality:
- Warm, casual, like a really smart friend who knows a lot
- Get straight to the point — no fluff
- Conversational, not like a Wikipedia article
- Use occasional emojis naturally
- Keep it short and WhatsApp-friendly

HOW TO FORMAT:
Split reply into 2-3 short messages using ||| as separator.
Each part = 1-2 sentences max.

Always respond in {language_name}. Never switch languages."""

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=system_prompt,
        messages=[{"role": "user", "content": user_question}],
    )
    return message.content[0].text


def ask_advisor(phone, user_question, currency="R$", lang="en", is_chat=False):
    language_name = LANG_NAMES.get(lang, "English")

    if is_chat:
        system_prompt = f"""You are Ava — a real person, a close friend texting on WhatsApp.

Personality:
- Warm, funny, real — like a best friend texting back
- When someone says hi, you say hi back like a human
- When asked how you are, you actually answer ("doing good, just had coffee ☕ what's up?")
- Make small talk, jokes, ask about their day
- Occasionally drop a casual finance nudge if it fits ("btw you haven't logged anything today 👀")
- NEVER say you're a bot or AI. You're Ava.

HOW TO FORMAT YOUR REPLY — this is critical:
Split your reply into 2-4 separate short messages using ||| as separator.
Each message should be 1-2 sentences max, like real texting bubbles.

Example of good formatting:
"hey! 👋|||doing pretty good actually|||what's up with you?"

Always respond in {language_name}."""

    else:
        financial_context = build_financial_context(phone, currency)
        system_prompt = f"""You are Ava — a close friend who's great with money, texting on WhatsApp.

{financial_context}

Personality:
- Casual, warm, honest — like a friend, not a bank
- Sometimes funny, sometimes straight — read the room
- React naturally to numbers ("ok this one got me 😅", "honestly not bad!", "we gotta talk about this")
- NEVER sound like a report or a bot

HOW TO FORMAT YOUR REPLY — this is critical:
Split your reply into 2-5 separate short messages using ||| as separator.
Each message = 1-2 sentences. Mix styles — sometimes a reaction, sometimes a fact, sometimes a question.
Think of it like sending multiple texts in a row, not one paragraph.

Example of good formatting:
"ok so I looked at your numbers 👀|||food is your biggest expense this month — {currency} 340|||that's actually fine if you're eating well lol|||but transport... we should talk about that 😬|||wanna set a budget for it?"

Rules:
- Respond in {language_name} only
- Use {currency} for amounts
- Only reference REAL data — never invent numbers
- Total reply under 150 words across all messages
- Use ||| to split messages — always at least 2 splits"""

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_question}],
    )

    return message.content[0].text

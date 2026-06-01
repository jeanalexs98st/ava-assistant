import os
import sqlite3
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", "finance.db")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def migrate_db():
    """Add missing columns to existing tables without losing data."""
    with get_db() as conn:
        migrations = [
            "ALTER TABLE user_settings ADD COLUMN briefing_time TEXT DEFAULT '08:00'",
            "ALTER TABLE user_settings ADD COLUMN briefing_enabled INTEGER DEFAULT 0",
            "ALTER TABLE user_settings ADD COLUMN report_frequency TEXT DEFAULT 'none'",
            "ALTER TABLE user_settings ADD COLUMN last_message TEXT DEFAULT ''",
            "ALTER TABLE user_settings ADD COLUMN last_reply TEXT DEFAULT ''",
        ]
        for sql in migrations:
            try:
                conn.execute(sql)
            except Exception:
                pass  # Column already exists, skip


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                type TEXT NOT NULL CHECK(type IN ('expense', 'income')),
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                category TEXT NOT NULL,
                limit_amount REAL NOT NULL,
                UNIQUE(phone, category)
            );

            CREATE TABLE IF NOT EXISTS user_settings (
                phone TEXT PRIMARY KEY,
                language TEXT NOT NULL DEFAULT 'en',
                briefing_time TEXT DEFAULT '08:00',
                briefing_enabled INTEGER DEFAULT 0,
                report_frequency TEXT DEFAULT 'none'
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                text TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                event_at TEXT NOT NULL,
                remind_before INTEGER DEFAULT 60,
                reminder_sent INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS recurring_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('expense', 'income')),
                day_of_month INTEGER NOT NULL,
                active INTEGER DEFAULT 1,
                last_logged TEXT
            );

            CREATE TABLE IF NOT EXISTS savings_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                name TEXT NOT NULL,
                target_amount REAL NOT NULL,
                saved_amount REAL DEFAULT 0,
                deadline TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                text TEXT NOT NULL,
                done INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                intent TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                name TEXT NOT NULL,
                birthday TEXT,
                relationship TEXT,
                notes TEXT
            );
        """)


# ─── Transactions ────────────────────────────────────────────
def add_transaction(phone, amount, category, description, tx_type):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO transactions (phone, amount, category, description, type) VALUES (?, ?, ?, ?, ?)",
            (phone, amount, category, description, tx_type),
        )


def get_monthly_summary(phone, year=None, month=None):
    now = datetime.now()
    year = year or now.year
    month = month or now.month
    month_str = f"{year}-{month:02d}"
    with get_db() as conn:
        return conn.execute(
            """SELECT category, type, SUM(amount) as total FROM transactions
               WHERE phone = ? AND strftime('%Y-%m', created_at) = ?
               GROUP BY category, type ORDER BY type, total DESC""",
            (phone, month_str),
        ).fetchall()


def get_recent_transactions(phone, limit=5):
    with get_db() as conn:
        return conn.execute(
            """SELECT amount, category, description, type, created_at FROM transactions
               WHERE phone = ? ORDER BY created_at DESC LIMIT ?""",
            (phone, limit),
        ).fetchall()


def get_category_spending_this_month(phone, category):
    now = datetime.now()
    month_str = f"{now.year}-{now.month:02d}"
    with get_db() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(amount), 0) as total FROM transactions
               WHERE phone = ? AND category = ? AND type = 'expense'
               AND strftime('%Y-%m', created_at) = ?""",
            (phone, category, month_str),
        ).fetchone()
    return row["total"] if row else 0


def delete_last_transaction(phone):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM transactions WHERE phone = ? ORDER BY created_at DESC LIMIT 1", (phone,)
        ).fetchone()
        if row:
            conn.execute("DELETE FROM transactions WHERE id = ?", (row["id"],))
            return True
    return False


# ─── Budgets ─────────────────────────────────────────────────
def set_budget(phone, category, limit_amount):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO budgets (phone, category, limit_amount) VALUES (?, ?, ?) "
            "ON CONFLICT(phone, category) DO UPDATE SET limit_amount = excluded.limit_amount",
            (phone, category, limit_amount),
        )


def get_budgets(phone):
    with get_db() as conn:
        return conn.execute(
            "SELECT category, limit_amount FROM budgets WHERE phone = ?", (phone,)
        ).fetchall()


# ─── User Settings ───────────────────────────────────────────
def get_language(phone):
    with get_db() as conn:
        row = conn.execute("SELECT language FROM user_settings WHERE phone = ?", (phone,)).fetchone()
    return row["language"] if row else "en"


def set_language(phone, language):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO user_settings (phone, language) VALUES (?, ?) "
            "ON CONFLICT(phone) DO UPDATE SET language = excluded.language",
            (phone, language),
        )


def get_settings(phone):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM user_settings WHERE phone = ?", (phone,)).fetchone()
    return dict(row) if row else {"language": "en", "briefing_time": "08:00", "briefing_enabled": 0, "report_frequency": "none"}


def update_settings(phone, **kwargs):
    settings = get_settings(phone)
    settings.update(kwargs)
    with get_db() as conn:
        conn.execute(
            """INSERT INTO user_settings (phone, language, briefing_time, briefing_enabled, report_frequency)
               VALUES (:phone, :language, :briefing_time, :briefing_enabled, :report_frequency)
               ON CONFLICT(phone) DO UPDATE SET
               language=excluded.language, briefing_time=excluded.briefing_time,
               briefing_enabled=excluded.briefing_enabled, report_frequency=excluded.report_frequency""",
            {"phone": phone, **settings},
        )


def log_usage(phone, intent):
    with get_db() as conn:
        conn.execute("INSERT INTO usage_log (phone, intent) VALUES (?, ?)", (phone, intent))


def get_usage_stats(phone):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT intent, COUNT(*) as count FROM usage_log WHERE phone = ? GROUP BY intent",
            (phone,)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) as c FROM usage_log WHERE phone = ?", (phone,)).fetchone()["c"]
        days = conn.execute(
            "SELECT COUNT(DISTINCT date(created_at)) as d FROM usage_log WHERE phone = ?", (phone,)
        ).fetchone()["d"]
    return {
        "by_intent": {r["intent"]: r["count"] for r in rows},
        "total_messages": total,
        "days_active": days,
        "is_personalized": total >= 20
    }


def get_primary_phone():
    """Get the main user's phone number."""
    with get_db() as conn:
        row = conn.execute("SELECT phone FROM usage_log ORDER BY created_at DESC LIMIT 1").fetchone()
        if not row:
            row = conn.execute("SELECT phone FROM user_settings LIMIT 1").fetchone()
        if not row:
            row = conn.execute("SELECT phone FROM transactions LIMIT 1").fetchone()
    return row["phone"] if row else None


def get_last_context(phone):
    with get_db() as conn:
        row = conn.execute("SELECT last_message, last_reply FROM user_settings WHERE phone = ?", (phone,)).fetchone()
    if row:
        return row["last_message"] or "", row["last_reply"] or ""
    return "", ""


def set_last_context(phone, message, reply):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO user_settings (phone, language, last_message, last_reply) VALUES (?, 'en', ?, ?) "
            "ON CONFLICT(phone) DO UPDATE SET last_message = excluded.last_message, last_reply = excluded.last_reply",
            (phone, message[:500], reply[:500]),
        )


# ─── Reminders ───────────────────────────────────────────────
def add_reminder(phone, text, remind_at):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO reminders (phone, text, remind_at) VALUES (?, ?, ?)",
            (phone, text, remind_at),
        )


def get_pending_reminders(phone):
    with get_db() as conn:
        return conn.execute(
            "SELECT id, text, remind_at FROM reminders WHERE phone = ? AND sent = 0 ORDER BY remind_at",
            (phone,),
        ).fetchall()


def get_due_reminders():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_db() as conn:
        return conn.execute(
            "SELECT id, phone, text FROM reminders WHERE remind_at <= ? AND sent = 0", (now,)
        ).fetchall()


def mark_reminder_sent(reminder_id):
    with get_db() as conn:
        conn.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))


def delete_reminder(phone, reminder_id):
    with get_db() as conn:
        conn.execute("DELETE FROM reminders WHERE id = ? AND phone = ?", (reminder_id, phone))


# ─── Events / Calendar ───────────────────────────────────────
def add_event(phone, title, event_at, description="", remind_before=60):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO events (phone, title, description, event_at, remind_before) VALUES (?, ?, ?, ?, ?)",
            (phone, title, description, event_at, remind_before),
        )


def get_upcoming_events(phone, days=7):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    from datetime import timedelta
    future = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    with get_db() as conn:
        return conn.execute(
            "SELECT id, title, description, event_at FROM events WHERE phone = ? AND event_at BETWEEN ? AND ? ORDER BY event_at",
            (phone, now, future),
        ).fetchall()


def get_due_event_reminders():
    from datetime import timedelta
    now = datetime.now()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, phone, title, event_at, remind_before FROM events WHERE reminder_sent = 0 AND event_at > ?",
            (now.strftime("%Y-%m-%d %H:%M"),),
        ).fetchall()
    due = []
    for row in rows:
        event_time = datetime.strptime(row["event_at"], "%Y-%m-%d %H:%M")
        remind_time = event_time - timedelta(minutes=row["remind_before"])
        if now >= remind_time:
            due.append(row)
    return due


def mark_event_reminder_sent(event_id):
    with get_db() as conn:
        conn.execute("UPDATE events SET reminder_sent = 1 WHERE id = ?", (event_id,))


def delete_event(phone, event_id):
    with get_db() as conn:
        conn.execute("DELETE FROM events WHERE id = ? AND phone = ?", (event_id, phone))


# ─── Recurring Transactions ──────────────────────────────────
def add_recurring(phone, amount, category, description, tx_type, day_of_month):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO recurring_transactions (phone, amount, category, description, type, day_of_month) VALUES (?, ?, ?, ?, ?, ?)",
            (phone, amount, category, description, tx_type, day_of_month),
        )


def get_recurring(phone):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM recurring_transactions WHERE phone = ? AND active = 1", (phone,)
        ).fetchall()


def get_due_recurring():
    today = datetime.now().day
    today_str = datetime.now().strftime("%Y-%m")
    with get_db() as conn:
        return conn.execute(
            """SELECT * FROM recurring_transactions WHERE active = 1 AND day_of_month = ?
               AND (last_logged IS NULL OR strftime('%Y-%m', last_logged) != ?)""",
            (today, today_str),
        ).fetchall()


def mark_recurring_logged(rec_id):
    with get_db() as conn:
        conn.execute(
            "UPDATE recurring_transactions SET last_logged = ? WHERE id = ?",
            (datetime.now().strftime("%Y-%m-%d"), rec_id),
        )


# ─── Savings Goals ───────────────────────────────────────────
def add_savings_goal(phone, name, target_amount, deadline=None):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO savings_goals (phone, name, target_amount, deadline) VALUES (?, ?, ?, ?)",
            (phone, name, target_amount, deadline),
        )


def get_savings_goals(phone):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM savings_goals WHERE phone = ? ORDER BY created_at DESC", (phone,)
        ).fetchall()


def add_to_goal(phone, goal_name, amount):
    with get_db() as conn:
        conn.execute(
            "UPDATE savings_goals SET saved_amount = saved_amount + ? WHERE phone = ? AND LOWER(name) LIKE ?",
            (amount, phone, f"%{goal_name.lower()}%"),
        )


# ─── To-Do List ──────────────────────────────────────────────
def add_todo(phone, text):
    with get_db() as conn:
        conn.execute("INSERT INTO todos (phone, text) VALUES (?, ?)", (phone, text))


def get_todos(phone):
    with get_db() as conn:
        return conn.execute(
            "SELECT id, text, done FROM todos WHERE phone = ? AND done = 0 ORDER BY created_at", (phone,)
        ).fetchall()


def complete_todo(phone, todo_id=None, text_match=None):
    with get_db() as conn:
        if todo_id:
            conn.execute("UPDATE todos SET done = 1 WHERE id = ? AND phone = ?", (todo_id, phone))
        elif text_match:
            conn.execute(
                "UPDATE todos SET done = 1 WHERE phone = ? AND LOWER(text) LIKE ? AND done = 0",
                (phone, f"%{text_match.lower()}%"),
            )
        else:
            # Complete the oldest pending todo
            row = conn.execute(
                "SELECT id FROM todos WHERE phone = ? AND done = 0 ORDER BY created_at LIMIT 1", (phone,)
            ).fetchone()
            if row:
                conn.execute("UPDATE todos SET done = 1 WHERE id = ?", (row["id"],))


# ─── Notes / Memory ──────────────────────────────────────────
def add_note(phone, title, content):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO notes (phone, title, content) VALUES (?, ?, ?)", (phone, title, content)
        )


def get_notes(phone):
    with get_db() as conn:
        return conn.execute(
            "SELECT id, title, content, created_at FROM notes WHERE phone = ? ORDER BY created_at DESC", (phone,)
        ).fetchall()


def search_notes(phone, query):
    with get_db() as conn:
        return conn.execute(
            "SELECT id, title, content FROM notes WHERE phone = ? AND (LOWER(title) LIKE ? OR LOWER(content) LIKE ?)",
            (phone, f"%{query.lower()}%", f"%{query.lower()}%"),
        ).fetchall()


def delete_note(phone, note_id):
    with get_db() as conn:
        conn.execute("DELETE FROM notes WHERE id = ? AND phone = ?", (note_id, phone))


# ─── Contacts & Birthdays ────────────────────────────────────
def add_contact(phone, name, birthday=None, relationship=None, notes=None):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO contacts (phone, name, birthday, relationship, notes) VALUES (?, ?, ?, ?, ?)",
            (phone, name, birthday, relationship, notes),
        )


def get_contacts(phone):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM contacts WHERE phone = ? ORDER BY name", (phone,)
        ).fetchall()


def get_upcoming_birthdays(phone, days=7):
    from datetime import timedelta
    now = datetime.now()
    upcoming = []
    with get_db() as conn:
        contacts = conn.execute(
            "SELECT * FROM contacts WHERE phone = ? AND birthday IS NOT NULL", (phone,)
        ).fetchall()
    for c in contacts:
        try:
            bday = datetime.strptime(c["birthday"], "%m-%d").replace(year=now.year)
            if bday < now.replace(hour=0, minute=0):
                bday = bday.replace(year=now.year + 1)
            if (bday - now).days <= days:
                upcoming.append((c["name"], bday, c["relationship"]))
        except Exception:
            pass
    return sorted(upcoming, key=lambda x: x[1])


def get_due_birthday_reminders(phone):
    from datetime import timedelta
    now = datetime.now()
    due = []
    with get_db() as conn:
        contacts = conn.execute(
            "SELECT * FROM contacts WHERE phone = ? AND birthday IS NOT NULL", (phone,)
        ).fetchall()
    for c in contacts:
        try:
            bday = datetime.strptime(c["birthday"], "%m-%d").replace(year=now.year)
            diff = (bday.date() - now.date()).days
            if diff in (3, 1, 0):  # remind 3 days before, 1 day before, and on the day
                due.append((c["name"], bday, c["relationship"], diff))
        except Exception:
            pass
    return due

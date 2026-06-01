import os
import time
import threading
import database as db
from twilio.rest import Client

TWILIO_FROM = "whatsapp:+14155238886"


def send_whatsapp(phone, message):
    client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    client.messages.create(body=message, from_=TWILIO_FROM, to=phone)


def check_and_send_reminders():
    """Check for due reminders and send them via WhatsApp."""
    while True:
        try:
            due = db.get_due_reminders()
            for row in due:
                try:
                    lang = db.get_language(row["phone"])
                    if lang == "pt":
                        msg = f"⏰ *Lembrete de Mort:* {row['text']}"
                    elif lang == "es":
                        msg = f"⏰ *Recordatorio de Mort:* {row['text']}"
                    else:
                        msg = f"⏰ *Reminder from Mort:* {row['text']}"
                    send_whatsapp(row["phone"], msg)
                    db.mark_reminder_sent(row["id"])
                except Exception as e:
                    print(f"❌ Failed to send reminder {row['id']}: {e}")
        except Exception as e:
            print(f"❌ Reminder check error: {e}")
        time.sleep(30)  # Check every 30 seconds


def start_scheduler():
    thread = threading.Thread(target=check_and_send_reminders, daemon=True)
    thread.start()
    print("⏰ Reminder scheduler started.")

import os
from dotenv import load_dotenv
load_dotenv()

# Debug: check environment variables
anthropic_key = os.getenv("ANTHROPIC_API_KEY", "NOT SET")
print(f"🔑 ANTHROPIC_API_KEY: {anthropic_key[:15]}..." if anthropic_key != "NOT SET" else "❌ ANTHROPIC_API_KEY NOT SET")
print(f"🔑 TWILIO_SID: {os.getenv('TWILIO_ACCOUNT_SID', 'NOT SET')[:10]}...")

import database as db
import scheduler
from app import app

db.init_db()
db.migrate_db()
scheduler.start_scheduler()

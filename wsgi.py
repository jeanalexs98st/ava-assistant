from dotenv import load_dotenv
load_dotenv()

import database as db
import scheduler
from app import app

db.init_db()
db.migrate_db()
scheduler.start_scheduler()

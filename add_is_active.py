# add_is_active.py — one-time script to add is_active column and mark HR active
import sqlite3
import os

DB = 'interview_app.db' # make sure this path is correct

if not os.path.exists(DB):
    alt = os.path.join('instance','interview_app.db')
    if os.path.exists(alt):
        DB=alt
if not os.path.exists(DB):
    print("Database file not found:", DB)
    raise SystemExit(1)

conn = sqlite3.connect(DB)
cur = conn.cursor()

# 1) Add column is_active if it doesn't exist
try:
    cur.execute("ALTER TABLE user ADD COLUMN is_active BOOLEAN DEFAULT 0;")
    print("Added column is_active (default 0).")
except Exception as e:
    # if it already exists, sqlite raises an error — ignore
    print("Could not add column (maybe already exists):", e)

# 2) Make sure HR user (if exists) is active
try:
    cur.execute("UPDATE user SET is_active = 1 WHERE role = 'HR';")
    print("Set is_active=1 for role='HR' users (if any).")
except Exception as e:
    print("Could not update HR is_active:", e)

conn.commit()
conn.close()
print("Done. Please restart your Flask app.")
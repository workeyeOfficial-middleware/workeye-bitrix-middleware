import sqlite3
import json
from datetime import datetime, timedelta
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "screenshots_cache.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS screenshots (
        id INTEGER PRIMARY KEY,
        member_id INTEGER,
        member_name TEXT,
        member_email TEXT,
        timestamp TEXT,
        image_url TEXT,
        screenshot_url TEXT,
        is_valid INTEGER,
        date TEXT,
        raw_json TEXT,
        saved_at TEXT
    )''')
    conn.commit()
    conn.close()

def save_screenshots(screenshots: list):
    purge_old_screenshots()  # Clean up expired screenshots whenever new ones are saved
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    for s in screenshots:
        sid = s.get("id")
        if not sid:
            continue
        ts = s.get("timestamp","")
        date = ts[:10] if ts else ""
        c.execute('''INSERT OR REPLACE INTO screenshots
            (id, member_id, member_name, member_email, timestamp, image_url, screenshot_url, is_valid, date, raw_json, saved_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (sid, s.get("member_id"), s.get("member_name"), s.get("member_email"),
             ts, s.get("image_url",""), s.get("screenshot_url",""),
             1 if s.get("is_valid") else 0,
             date, json.dumps(s), now))
    conn.commit()
    conn.close()

def purge_old_screenshots(retention_days: int = 30):
    """Delete screenshots older than retention_days. Call this on a schedule or at save time."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    c.execute("DELETE FROM screenshots WHERE date < ?", (cutoff,))
    conn.commit()
    conn.close()

def get_screenshots_by_date(date: str = None) -> list:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if date:
        c.execute("SELECT raw_json FROM screenshots WHERE date=? ORDER BY timestamp DESC", (date,))
    else:
        # Only return screenshots within the 7-day retention window
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        c.execute("SELECT raw_json FROM screenshots WHERE date >= ? ORDER BY timestamp DESC", (cutoff,))
    rows = c.fetchall()
    conn.close()
    return [json.loads(r[0]) for r in rows]

def get_screenshots_by_member_date(member_id: int, date: str = None) -> list:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if date:
        c.execute("SELECT raw_json FROM screenshots WHERE member_id=? AND date=? ORDER BY timestamp DESC",
                  (member_id, date))
    else:
        # Only return screenshots within the 7-day retention window
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        c.execute("SELECT raw_json FROM screenshots WHERE member_id=? AND date >= ? ORDER BY timestamp DESC",
                  (member_id, cutoff))
    rows = c.fetchall()
    conn.close()
    return [json.loads(r[0]) for r in rows]

init_db()
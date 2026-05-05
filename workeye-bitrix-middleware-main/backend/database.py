"""
database.py
===========
SQLite database to store Bitrix24 portal tokens.

When a customer installs your app from the marketplace,
Bitrix24 sends tokens — this file saves them so you never lose them.

Table: portals
- member_id   → unique ID of the customer's Bitrix24 portal
- domain      → their portal URL e.g. company.bitrix24.com
- access_token  → used to make API calls (expires every 1 hour)
- refresh_token → used to get a new access_token (never expires)
- expires_at  → when the access_token expires
- created_at  → when the app was installed
"""

import sqlite3
import os
from datetime import datetime, timedelta

# Database file location — stored in backend folder
DB_PATH = os.path.join(os.path.dirname(__file__), "portals.db")


# =========================
# SETUP — Run once on startup
# =========================
def init_db():
    """
    Creates the database and portals table if they don't exist yet.
    Call this once when your app starts.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portals (
            member_id     TEXT PRIMARY KEY,
            domain        TEXT NOT NULL,
            access_token  TEXT NOT NULL,
            refresh_token TEXT NOT NULL,
            expires_at    TEXT NOT NULL,
            created_at    TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print("[DB] ✅ Database ready")


# =========================
# SAVE — When app is installed
# =========================
def save_portal(member_id: str, domain: str, access_token: str, refresh_token: str, expires_in: int = 3600):
    """
    Saves or updates a portal's tokens.
    Called from bitrix_routes.py when a customer installs your app.

    Args:
        member_id     → Bitrix24 portal unique ID
        domain        → e.g. company.bitrix24.com
        access_token  → token to make API calls
        refresh_token → token to refresh access_token
        expires_in    → seconds until access_token expires (default 3600 = 1 hour)
    """
    expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()
    created_at = datetime.utcnow().isoformat()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # INSERT or UPDATE if portal already exists
    cursor.execute("""
        INSERT INTO portals (member_id, domain, access_token, refresh_token, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(member_id) DO UPDATE SET
            domain        = excluded.domain,
            access_token  = excluded.access_token,
            refresh_token = excluded.refresh_token,
            expires_at    = excluded.expires_at
    """, (member_id, domain, access_token, refresh_token, expires_at, created_at))

    conn.commit()
    conn.close()
    print(f"[DB] ✅ Portal saved: {member_id} ({domain})")


# =========================
# GET — Fetch a portal's tokens
# =========================
def get_portal(member_id: str) -> dict:
    """
    Returns a portal's saved tokens.
    Returns None if portal not found.

    Args:
        member_id → Bitrix24 portal unique ID

    Returns:
        {
            "member_id": "...",
            "domain": "...",
            "access_token": "...",
            "refresh_token": "...",
            "expires_at": "...",
            "created_at": "..."
        }
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # So we get dict-like rows
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM portals WHERE member_id = ?", (member_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return dict(row)
    return None


# =========================
# UPDATE — Save new tokens after refresh
# =========================
def update_tokens(member_id: str, access_token: str, refresh_token: str, expires_in: int = 3600):
    """
    Updates tokens after a refresh.
    Called from token_manager.py when access_token expires.

    Args:
        member_id     → Bitrix24 portal unique ID
        access_token  → new access token
        refresh_token → new refresh token
        expires_in    → seconds until new token expires
    """
    expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE portals
        SET access_token = ?, refresh_token = ?, expires_at = ?
        WHERE member_id = ?
    """, (access_token, refresh_token, expires_at, member_id))

    conn.commit()
    conn.close()
    print(f"[DB] ✅ Tokens refreshed for portal: {member_id}")


# =========================
# DELETE — When app is uninstalled
# =========================
def delete_portal(member_id: str):
    """
    Deletes all data for a portal.
    Called from bitrix_routes.py when a customer uninstalls your app.

    Args:
        member_id → Bitrix24 portal unique ID
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM portals WHERE member_id = ?", (member_id,))

    conn.commit()
    conn.close()
    print(f"[DB] ✅ Portal deleted: {member_id}")


# =========================
# LIST — See all installed portals
# =========================
def list_portals() -> list:
    """
    Returns all portals that have installed your app.
    Useful for admin/debugging.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT member_id, domain, expires_at, created_at FROM portals")
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


# =========================
# CHECK — Is token expired?
# =========================
def is_token_expired(member_id: str) -> bool:
    """
    Checks if the access_token for a portal has expired.
    Returns True if expired, False if still valid.
    """
    portal = get_portal(member_id)
    if not portal:
        return True

    expires_at = datetime.fromisoformat(portal["expires_at"])
    # Consider expired 5 minutes early to be safe
    return datetime.utcnow() >= (expires_at - timedelta(minutes=5))
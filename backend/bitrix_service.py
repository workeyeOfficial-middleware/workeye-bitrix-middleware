"""
bitrix_service.py — Drive Version
====================================
Sync saves reports as .txt files in Bitrix24 Shared Drive.

Where to see saved files:
  Bitrix24 → Drive → Shared Drive → WorkEye Reports folder
"""

import os
import base64
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

BITRIX_WEBHOOK = os.getenv("BITRIX_WEBHOOK")
SHARED_DRIVE_ID = "3"  # Shared Drive ID


# ─────────────────────────────────────────────
# Low-level helper
# ─────────────────────────────────────────────

def _call(method, payload=None, params=None):
    url = f"{BITRIX_WEBHOOK.rstrip('/')}/{method}.json"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    try:
        r = requests.post(url, json=payload or {}, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"[Bitrix] ERROR {method}: {e}")
        return {"error": str(e)}


# ─────────────────────────────────────────────
# Get or Create WorkEye Reports Folder
# ─────────────────────────────────────────────

def get_or_create_folder():
    """
    Looks for 'WorkEye Reports' folder in Shared Drive.
    Creates it if not found.
    Returns folder ID.
    """
    # Get children of Shared Drive
    result = _call("disk.folder.getchildren", params={"id": SHARED_DRIVE_ID})
    items = result.get("result", [])

    # Check if folder already exists
    for item in items:
        if item.get("NAME") == "WorkEye Reports" and item.get("TYPE") == "folder":
            print(f"[Bitrix] Found existing folder ID: {item['ID']}")
            return item["ID"]

    # Create folder if not found
    result = _call("disk.folder.addsubfolder", params={"id": SHARED_DRIVE_ID}, payload={
        "data": {"NAME": "WorkEye Reports"}
    })
    folder = result.get("result", {})
    folder_id = folder.get("ID")
    print(f"[Bitrix] Created new folder ID: {folder_id}")
    return folder_id


# ─────────────────────────────────────────────
# Save File to Drive
# ─────────────────────────────────────────────

def save_to_drive(filename, content):
    """
    Saves a text file inside WorkEye Reports folder in Shared Drive.
    Visible at: Bitrix24 → Drive → Shared Drive → WorkEye Reports
    """
    folder_id = get_or_create_folder()
    if not folder_id:
        print("[Bitrix] ERROR: Could not get folder ID")
        return {"success": False, "error": "Could not get folder"}

    # Encode content to base64
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    result = _call(
        "disk.folder.uploadfile",
        payload={
            "data": {"NAME": filename},
            "fileContent": encoded
        },
        params={"id": folder_id}
    )

    file_id = result.get("result", {}).get("ID")
    detail_url = result.get("result", {}).get("DETAIL_URL", "")

    if file_id:
        print(f"[Bitrix] File saved: {filename} (ID: {file_id})")
        return {"success": True, "file_id": file_id, "url": detail_url}
    else:
        print(f"[Bitrix] ERROR saving file: {result}")
        return {"success": False, "error": str(result)}


# ─────────────────────────────────────────────
# Sync: Dashboard Stats
# ─────────────────────────────────────────────

def sync_dashboard(stats_response):
    payload = stats_response.get("data", stats_response)
    stats   = payload.get("stats", {})
    members = payload.get("members", [])
    date    = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"WorkEye Dashboard Report",
        f"Date     : {date}",
        f"Synced at: {now_str}",
        f"",
        f"Total Members    : {stats.get('total_members', 0)}",
        f"Active Now       : {stats.get('active_now', 0)}",
        f"Idle             : {stats.get('idle_now', 0)}",
        f"Offline          : {stats.get('offline', 0)}",
        f"Avg Productivity : {stats.get('average_productivity', 0)}%",
        f"",
        f"── Members ─────────────────────────────────",
    ]
    for m in members:
        status = m.get('status', '?')
        icon = {"active": "[Active]", "idle": "[Idle]", "offline": "[Offline]"}.get(status, "[?]")
        lines.append(
            f"{icon} {m.get('name','?')} | "
            f"Productivity: {m.get('productivity', 0)}% | "
            f"Screen: {_fmt_seconds(m.get('screen_time', 0))}"
        )

    filename = f"Dashboard_Report_{date}.txt"
    return save_to_drive(filename, "\n".join(lines))


# ─────────────────────────────────────────────
# Sync: Employees
# ─────────────────────────────────────────────

def sync_employees(members):
    date    = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"WorkEye Employee Report",
        f"Date     : {date}",
        f"Synced at: {now_str}",
        f"Total    : {len(members)}",
        f"",
        f"── Employees ───────────────────────────────",
    ]
    for i, m in enumerate(members, 1):
        status = m.get('status', '?')
        icon = {"active": "[Active]", "idle": "[Idle]", "offline": "[Offline]"}.get(status, "[?]")
        lines.append(
            f"{i}. {icon} {m.get('name','--')} | "
            f"{m.get('position','--')} | "
            f"{m.get('department','--')} | "
            f"Productivity: {m.get('productivity', 0)}%"
        )

    filename = f"Employee_Report_{date}.txt"
    return save_to_drive(filename, "\n".join(lines))


# ─────────────────────────────────────────────
# Sync: Attendance
# ─────────────────────────────────────────────

def sync_attendance(members):
    date    = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"WorkEye Attendance Report",
        f"Date     : {date}",
        f"Synced at: {now_str}",
        f"Total    : {len(members)}",
        f"",
        f"── Attendance ──────────────────────────────",
    ]
    for i, m in enumerate(members, 1):
        punch = "[IN]" if m.get("is_punched_in") else "[OUT]"
        pin   = m.get("punch_in_time",  "--")
        pout  = m.get("punch_out_time", "--")
        pin   = pin[11:16]  if pin  and len(pin)  > 10 else "--"
        pout  = pout[11:16] if pout and len(pout) > 10 else "--"
        lines.append(
            f"{i}. {punch} {m.get('name','--')} | "
            f"In: {pin} | Out: {pout} | "
            f"Hours: {m.get('today_hours', 0)}h | "
            f"{m.get('status','--')}"
        )

    filename = f"Attendance_Report_{date}.txt"
    return save_to_drive(filename, "\n".join(lines))


# ─────────────────────────────────────────────
# Sync: Screenshots
# ─────────────────────────────────────────────

def sync_screenshots(screenshots):
    date    = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"WorkEye Screenshots Report",
        f"Date     : {date}",
        f"Synced at: {now_str}",
        f"Total    : {len(screenshots)}",
        f"",
        f"── Screenshots ─────────────────────────────",
    ]
    for i, s in enumerate(screenshots, 1):
        ts      = s.get("timestamp", "")
        date_p  = ts[:10]   if ts else "--"
        time_p  = ts[11:19] if len(ts) > 10 else "--"
        size_kb = f"{s.get('file_size', 0) // 1024}KB" if s.get("file_size") else "--"
        valid   = "[Valid]" if s.get("is_valid") else "[Invalid]"
        name    = s.get("member_name") or s.get("name", "--")
        lines.append(
            f"{i}. {name} | {date_p} {time_p} | {size_kb} | {valid}"
        )

    filename = f"Screenshots_Report_{date}.txt"
    return save_to_drive(filename, "\n".join(lines))


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _fmt_seconds(secs):
    secs = int(secs or 0)
    h = secs // 3600
    m = (secs % 3600) // 60
    return f"{h}h {m:02d}m"


def _fmt_time(iso_str):
    if not iso_str:
        return "--"
    try:
        return iso_str[11:16]
    except Exception:
        return str(iso_str)
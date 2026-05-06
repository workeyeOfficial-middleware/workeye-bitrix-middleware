"""
bitrix_service.py — HTML Reports + CRM Timeline Comments
=========================================================
Saves 3 polished HTML report files to Bitrix24 Shared Drive every day.
Also posts a daily summary comment to the CRM timeline via REST API.

Drive files (open directly in browser from Bitrix Drive):
  WorkEye Reports/WorkEye_Daily_YYYY-MM-DD.html       — all employees, status, hours, productivity
  WorkEye Reports/WorkEye_Attendance_YYYY-MM-DD.html  — punch-in/out times, hours worked
  WorkEye Reports/WorkEye_Employee_YYYY-MM-DD.html    — name, position, dept, productivity

CRM:
  crm.timeline.comment.add  — posts a text summary to every CRM contact that
                               matches an employee email address.
"""

import os
import base64
import requests
import io
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

try:
    from weasyprint import HTML as WeasyprintHTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    print("[Bitrix] WARNING: weasyprint not installed. Run: pip install weasyprint")

load_dotenv()

BITRIX_WEBHOOK = os.getenv("BITRIX_WEBHOOK", "").rstrip("/")
SHARED_DRIVE_ID = "3"

IST = timezone(timedelta(hours=5, minutes=30))


# ─────────────────────────────────────────────────────────────────────────────
# Low-level Bitrix REST helper
# ─────────────────────────────────────────────────────────────────────────────

def _call(method, payload=None, params=None):
    """
    POST to Bitrix24 REST webhook.
    All parameters go in the JSON body — Bitrix accepts them either way,
    but mixing URL params + JSON body causes 400s on some methods.
    We do NOT call raise_for_status() so we always get the error body back.
    """
    if not BITRIX_WEBHOOK:
        print("[Bitrix] ERROR: BITRIX_WEBHOOK not set")
        return {"error": "BITRIX_WEBHOOK not configured"}
    url = f"{BITRIX_WEBHOOK}/{method}.json"
    body = dict(payload or {})
    if params:
        body.update(params)          # merge params into body — never use URL params
    try:
        r = requests.post(url, json=body, timeout=30)
        data = r.json()
        if r.status_code >= 400:
            err = data.get("error_description") or data.get("error") or str(data)
            print(f"[Bitrix] HTTP {r.status_code} on {method}: {err}")
            return {"error": f"HTTP {r.status_code}: {err}"}
        return data
    except requests.exceptions.RequestException as e:
        print(f"[Bitrix] ERROR {method}: {e}")
        return {"error": str(e)}


def _get_shared_storage_id() -> str:
    """
    Auto-discover the correct shared-drive storage ID for this portal.
    Falls back to SHARED_DRIVE_ID if discovery fails.
    Bitrix shared drive is TYPE=shared; its ID varies per portal.
    """
    result = _call("disk.storage.getlist")
    for s in result.get("result", []):
        if s.get("CODE") == "shared" or s.get("TYPE") == "shared":
            sid = str(s["ID"])
            print(f"[Bitrix] Shared storage ID: {sid}")
            return sid
    print(f"[Bitrix] WARNING: could not discover shared storage — using default {SHARED_DRIVE_ID}")
    return SHARED_DRIVE_ID


# ─────────────────────────────────────────────────────────────────────────────
# Drive helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create_folder():
    storage_id = _get_shared_storage_id()
    # List children of the storage root
    result = _call("disk.storage.getchildren", {"id": storage_id})
    for item in result.get("result", []):
        if item.get("NAME") == "WorkEye Reports" and item.get("TYPE") == "folder":
            print(f"[Bitrix] Found folder ID: {item['ID']}")
            return str(item["ID"])
    # Create it
    result = _call("disk.storage.addfolder", {"id": storage_id, "data": {"NAME": "WorkEye Reports"}})
    folder = result.get("result", {})
    folder_id = folder.get("ID")
    if folder_id:
        print(f"[Bitrix] Created folder ID: {folder_id}")
        return str(folder_id)
    print(f"[Bitrix] ERROR creating folder: {result}")
    return None


def save_to_drive(filename, html_content):
    """
    Upload an HTML file to the WorkEye Reports folder on Bitrix24 Shared Drive.
    Uses disk.folder.uploadfile with fileContent as a plain base64 string.
    """
    folder_id = get_or_create_folder()
    if not folder_id:
        return {"success": False, "error": "Could not get/create WorkEye Reports folder"}

    encoded = base64.b64encode(html_content.encode("utf-8")).decode("utf-8")

    # Correct Bitrix24 disk.folder.uploadfile payload:
    # id           → folder ID (in body, not URL)
    # data.NAME    → filename shown in Drive
    # fileContent  → plain base64 string (NOT a list, NOT multipart)
    result = _call("disk.folder.uploadfile", {
        "id":          folder_id,
        "data":        {"NAME": filename},
        "fileContent": encoded,
    })

    file_result  = result.get("result") or {}
    if isinstance(file_result, dict):
        file_id      = file_result.get("ID")
        detail_url   = file_result.get("DETAIL_URL", "")
        download_url = file_result.get("DOWNLOAD_URL", "")
    else:
        file_id = None

    if file_id:
        print(f"[Bitrix] ✅ Uploaded: {filename} (ID: {file_id})")
        return {"success": True, "file_id": file_id, "url": detail_url, "download_url": download_url}
    else:
        err = result.get("error", str(result))
        print(f"[Bitrix] ❌ Upload failed for {filename}: {err}")
        return {"success": False, "error": err}


# ─────────────────────────────────────────────────────────────────────────────
# HTML → PDF converter
# ─────────────────────────────────────────────────────────────────────────────

def _html_to_pdf_bytes(html_content):
    """Convert HTML string to PDF bytes using weasyprint."""
    if not WEASYPRINT_AVAILABLE:
        raise RuntimeError("weasyprint is not installed. Run: pip install weasyprint")
    buf = io.BytesIO()
    WeasyprintHTML(string=html_content).write_pdf(buf)
    return buf.getvalue()


def save_pdf_to_drive(filename, html_content):
    """Convert HTML to PDF and upload to Bitrix24 Drive."""
    folder_id = get_or_create_folder()
    if not folder_id:
        return {"success": False, "error": "Could not get/create folder"}
    pdf_bytes = _html_to_pdf_bytes(html_content)
    encoded   = base64.b64encode(pdf_bytes).decode("utf-8")
    result    = _call("disk.folder.uploadfile", {
        "id": folder_id, "data": {"NAME": filename}, "fileContent": encoded,
    })
    file_id    = result.get("result", {}).get("ID")
    detail_url = result.get("result", {}).get("DETAIL_URL", "")
    if file_id:
        print(f"[Bitrix] Uploaded PDF: {filename} (ID: {file_id})")
        return {"success": True, "file_id": file_id, "url": detail_url}
    else:
        print(f"[Bitrix] PDF Upload failed: {result}")
        return {"success": False, "error": str(result)}


# ─────────────────────────────────────────────────────────────────────────────
# HTML helpers
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f0f2f5; color: #1a1a2e; }
  .page { max-width: 960px; margin: 0 auto; padding: 24px 16px; }
  .header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
            color: #fff; border-radius: 12px; padding: 28px 32px; margin-bottom: 24px; }
  .header h1 { font-size: 22px; font-weight: 700; letter-spacing: .5px; }
  .header .meta { font-size: 13px; opacity: .75; margin-top: 6px; }
  .kpi-row { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 24px; }
  .kpi { flex: 1 1 140px; background: #fff; border-radius: 10px;
         padding: 18px 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  .kpi .val { font-size: 30px; font-weight: 700; }
  .kpi .lbl { font-size: 12px; color: #777; margin-top: 4px; text-transform: uppercase; letter-spacing: .4px; }
  .kpi.green .val { color: #10b981; }
  .kpi.blue  .val { color: #3b82f6; }
  .kpi.amber .val { color: #f59e0b; }
  .kpi.red   .val { color: #ef4444; }
  table { width: 100%; border-collapse: collapse; background: #fff;
          border-radius: 10px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  thead tr { background: #1a1a2e; color: #fff; }
  thead th { padding: 12px 14px; text-align: left; font-size: 12px;
             font-weight: 600; letter-spacing: .5px; text-transform: uppercase; }
  tbody tr:nth-child(even) { background: #f8f9fb; }
  tbody tr:hover { background: #eff6ff; }
  tbody td { padding: 11px 14px; font-size: 13px; border-bottom: 1px solid #f0f0f0; }
  .badge { display: inline-block; padding: 3px 9px; border-radius: 20px;
           font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .4px; }
  .badge-active  { background: #d1fae5; color: #065f46; }
  .badge-idle    { background: #fef3c7; color: #92400e; }
  .badge-offline { background: #f3f4f6; color: #6b7280; }
  .badge-in      { background: #dbeafe; color: #1e40af; }
  .badge-out     { background: #fce7f3; color: #9d174d; }
  .prod-bar { height: 6px; border-radius: 3px; background: #e5e7eb; overflow: hidden; min-width: 60px; }
  .prod-fill { height: 100%; border-radius: 3px; background: linear-gradient(90deg, #3b82f6, #10b981); }
  .section-title { font-size: 15px; font-weight: 700; margin: 0 0 12px; color: #1a1a2e; }
  .table-wrap { margin-bottom: 28px; }
  footer { text-align: center; font-size: 12px; color: #aaa; margin-top: 20px; padding-bottom: 12px; }
</style>
"""

def _html_page(title, date_str, generated_str, body_html):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} – {date_str}</title>
  {_CSS}
</head>
<body>
<div class="page">
  <div class="header">
    <h1>📊 {title}</h1>
    <div class="meta">Date: {date_str} &nbsp;·&nbsp; Generated: {generated_str} IST</div>
  </div>
  {body_html}
  <footer>WorkEye × Bitrix24 Integration — Auto-generated report</footer>
</div>
</body>
</html>"""

def _badge(status):
    s = (status or "").lower()
    cls = {"active": "badge-active", "idle": "badge-idle", "offline": "badge-offline"}.get(s, "badge-offline")
    return f'<span class="badge {cls}">{status or "—"}</span>'

def _punch_badge(is_in):
    cls, lbl = ("badge-in", "Punched In") if is_in else ("badge-out", "Punched Out")
    return f'<span class="badge {cls}">{lbl}</span>'

def _prod_cell(pct):
    p = int(pct or 0)
    return (f'<div style="display:flex;align-items:center;gap:8px">'
            f'<span style="min-width:34px;font-weight:600">{p}%</span>'
            f'<div class="prod-bar"><div class="prod-fill" style="width:{p}%"></div></div>'
            f'</div>')

def _fmt_time(iso_str):
    if not iso_str: return "—"
    try: return str(iso_str)[11:16]
    except: return str(iso_str)

def _fmt_seconds(secs):
    secs = int(secs or 0)
    h, m = secs // 3600, (secs % 3600) // 60
    return f"{h}h {m:02d}m"


# ─────────────────────────────────────────────────────────────────────────────
# Report 1 — Daily Overview
# ─────────────────────────────────────────────────────────────────────────────

def generate_daily_report(stats_response):
    payload  = stats_response.get("data", stats_response)
    stats    = payload.get("stats", {})
    members  = payload.get("members", [])
    date_str = datetime.now(IST).strftime("%Y-%m-%d")
    now_str  = datetime.now(IST).strftime("%Y-%m-%d %H:%M")

    total    = stats.get("total_members", len(members))
    active   = stats.get("active_now",   sum(1 for m in members if (m.get("status","")).lower()=="active"))
    idle     = stats.get("idle_now",     sum(1 for m in members if (m.get("status","")).lower()=="idle"))
    offline  = stats.get("offline",      total - active - idle)
    avg_prod = stats.get("average_productivity", 0)

    kpis = (f'<div class="kpi-row">'
            f'<div class="kpi blue"><div class="val">{total}</div><div class="lbl">Total Employees</div></div>'
            f'<div class="kpi green"><div class="val">{active}</div><div class="lbl">Active Now</div></div>'
            f'<div class="kpi amber"><div class="val">{idle}</div><div class="lbl">Idle</div></div>'
            f'<div class="kpi red"><div class="val">{offline}</div><div class="lbl">Offline</div></div>'
            f'<div class="kpi blue"><div class="val">{int(avg_prod)}%</div><div class="lbl">Avg Productivity</div></div>'
            f'</div>')

    rows = "".join(
        f'<tr>'
        f'<td style="color:#6b7280;font-size:12px">{i}</td>'
        f'<td><strong>{m.get("name","—")}</strong></td>'
        f'<td>{m.get("email","—")}</td>'
        f'<td>{m.get("position","—")}</td>'
        f'<td>{m.get("department","—")}</td>'
        f'<td>{_badge(m.get("status"))}</td>'
        f'<td>{_fmt_seconds(m.get("screen_time",0))}</td>'
        f'<td>{_prod_cell(m.get("productivity",0))}</td>'
        f'</tr>'
        for i, m in enumerate(members, 1)
    )

    table = (f'<div class="table-wrap"><p class="section-title">Employee Status Overview</p>'
             f'<table><thead><tr><th>#</th><th>Name</th><th>Email</th><th>Position</th>'
             f'<th>Department</th><th>Status</th><th>Screen Time</th><th>Productivity</th>'
             f'</tr></thead><tbody>{rows}</tbody></table></div>')

    return _html_page("Daily Overview Report", date_str, now_str, kpis + table)


def sync_daily_report(stats_response):
    html     = generate_daily_report(stats_response)
    date_str = datetime.now(IST).strftime("%Y-%m-%d")
    return save_to_drive(f"WorkEye_Daily_{date_str}.html", html)


# ─────────────────────────────────────────────────────────────────────────────
# Report 2 — Attendance Report
# ─────────────────────────────────────────────────────────────────────────────

def generate_attendance_report(attendance):
    date_str    = datetime.now(IST).strftime("%Y-%m-%d")
    now_str     = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    punched_in  = sum(1 for m in attendance if m.get("is_punched_in"))
    punched_out = len(attendance) - punched_in

    kpis = (f'<div class="kpi-row">'
            f'<div class="kpi blue"><div class="val">{len(attendance)}</div><div class="lbl">Total Employees</div></div>'
            f'<div class="kpi green"><div class="val">{punched_in}</div><div class="lbl">Punched In</div></div>'
            f'<div class="kpi red"><div class="val">{punched_out}</div><div class="lbl">Not Punched In</div></div>'
            f'</div>')

    rows = "".join(
        f'<tr>'
        f'<td style="color:#6b7280;font-size:12px">{i}</td>'
        f'<td><strong>{m.get("name","—")}</strong></td>'
        f'<td>{m.get("position","—")}</td>'
        f'<td>{m.get("department","—")}</td>'
        f'<td>{_punch_badge(m.get("is_punched_in", False))}</td>'
        f'<td style="font-weight:600;color:#10b981">{_fmt_time(m.get("punch_in_time"))}</td>'
        f'<td style="color:#ef4444">{_fmt_time(m.get("punch_out_time"))}</td>'
        f'<td style="font-weight:600">{m.get("today_hours",0)}h</td>'
        f'</tr>'
        for i, m in enumerate(attendance, 1)
    )

    table = (f'<div class="table-wrap"><p class="section-title">Attendance Details</p>'
             f'<table><thead><tr><th>#</th><th>Name</th><th>Position</th><th>Department</th>'
             f'<th>Status</th><th>Punch In</th><th>Punch Out</th><th>Hours Worked</th>'
             f'</tr></thead><tbody>{rows}</tbody></table></div>')

    return _html_page("Attendance Report", date_str, now_str, kpis + table)


def sync_attendance(attendance_data):
    if isinstance(attendance_data, dict):
        members = attendance_data.get("members", attendance_data.get("attendance", []))
    else:
        members = attendance_data or []
    html     = generate_attendance_report(members)
    date_str = datetime.now(IST).strftime("%Y-%m-%d")
    return save_to_drive(f"WorkEye_Attendance_{date_str}.html", html)


# ─────────────────────────────────────────────────────────────────────────────
# Report 3 — Employee Report
# ─────────────────────────────────────────────────────────────────────────────

def generate_employee_report(members):
    date_str = datetime.now(IST).strftime("%Y-%m-%d")
    now_str  = datetime.now(IST).strftime("%Y-%m-%d %H:%M")

    rows = "".join(
        f'<tr>'
        f'<td style="color:#6b7280;font-size:12px">{i}</td>'
        f'<td><strong>{m.get("name","—")}</strong></td>'
        f'<td>{m.get("email","—")}</td>'
        f'<td>{m.get("position","—")}</td>'
        f'<td>{m.get("department","—")}</td>'
        f'<td>{_badge(m.get("status"))}</td>'
        f'<td>{m.get("devices","—")}</td>'
        f'<td>{_prod_cell(m.get("productivity",0))}</td>'
        f'<td>{_fmt_seconds(m.get("screen_time",0))}</td>'
        f'</tr>'
        for i, m in enumerate(members, 1)
    )

    table = (f'<div class="table-wrap"><p class="section-title">All Employees — {date_str}</p>'
             f'<table><thead><tr><th>#</th><th>Name</th><th>Email</th><th>Position</th>'
             f'<th>Department</th><th>Status</th><th>Devices</th><th>Productivity</th><th>Screen Time</th>'
             f'</tr></thead><tbody>{rows}</tbody></table></div>')

    return _html_page("Employee Report", date_str, now_str, table)


def sync_employees(members):
    html     = generate_employee_report(members)
    date_str = datetime.now(IST).strftime("%Y-%m-%d")
    return save_to_drive(f"WorkEye_Employee_{date_str}.html", html)


# ─────────────────────────────────────────────────────────────────────────────
# Legacy alias
# ─────────────────────────────────────────────────────────────────────────────

def sync_dashboard(stats_response):
    """Backward-compatible alias — called by the existing /sync-dashboard route."""
    return sync_daily_report(stats_response)


# ─────────────────────────────────────────────────────────────────────────────
# CRM: find contact by email
# ─────────────────────────────────────────────────────────────────────────────

def _find_crm_contact_id(email):
    result = _call("crm.contact.list", payload={
        "filter": {"EMAIL": email},
        "select": ["ID", "NAME"],
    })
    items = result.get("result", [])
    return str(items[0]["ID"]) if items else None


# ─────────────────────────────────────────────────────────────────────────────
# CRM: post timeline comment on a single contact
# ─────────────────────────────────────────────────────────────────────────────

def post_crm_timeline_comment(entity_id, comment):
    """
    Add a comment to a CRM Contact's timeline.
    Uses crm.timeline.comment.add — counts as a real Bitrix REST API call.
    """
    result = _call("crm.timeline.comment.add", payload={
        "fields": {
            "ENTITY_ID":   int(entity_id),
            "ENTITY_TYPE": "contact",
            "COMMENT":     comment,
            "AUTHOR_ID":   1,  # Bitrix admin user ID — change if needed
        }
    })
    comment_id = result.get("result")
    if comment_id:
        print(f"[Bitrix CRM] Posted timeline comment ID {comment_id} on contact {entity_id}")
        return {"success": True, "comment_id": comment_id}
    else:
        print(f"[Bitrix CRM] Failed for contact {entity_id}: {result}")
        return {"success": False, "error": str(result)}


# ─────────────────────────────────────────────────────────────────────────────
# CRM: post daily summary comments for all matched employees
# ─────────────────────────────────────────────────────────────────────────────

def post_daily_crm_comments(stats_response):
    """
    For every employee in stats_response, look up their Bitrix CRM Contact
    by email and post a daily productivity summary to their timeline.
    """
    payload  = stats_response.get("data", stats_response)
    members  = payload.get("members", [])
    date_str = datetime.now(IST).strftime("%Y-%m-%d")

    posted = skipped = errors = 0

    for m in members:
        email = m.get("email")
        if not email:
            skipped += 1
            continue

        contact_id = _find_crm_contact_id(email)
        if not contact_id:
            print(f"[Bitrix CRM] No CRM contact for {email} — skipping")
            skipped += 1
            continue

        status   = m.get("status", "unknown").capitalize()
        prod     = int(m.get("productivity") or 0)
        screen   = _fmt_seconds(m.get("screen_time", 0))
        position = m.get("position") or "Employee"
        dept     = m.get("department") or "—"

        comment = (
            f"📊 WorkEye Daily Report — {date_str}\n"
            f"Employee : {m.get('name','—')} ({position} / {dept})\n"
            f"Status   : {status}\n"
            f"Productivity : {prod}%\n"
            f"Screen Time  : {screen}\n"
            f"——————————————————\n"
            f"Auto-generated by WorkEye × Bitrix24 integration."
        )

        r = post_crm_timeline_comment(contact_id, comment)
        if r.get("success"): posted += 1
        else:                 errors += 1

    print(f"[Bitrix CRM] Comments: posted={posted} skipped={skipped} errors={errors}")
    return {"posted": posted, "skipped": skipped, "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────
# All-in-one: 3 HTML reports + CRM comments (called by auto_reporter.py)
# ─────────────────────────────────────────────────────────────────────────────

def run_all_reports(stats_response, attendance=None):
    """
    Generates and uploads all 3 HTML reports to Bitrix Drive,
    then posts CRM timeline comments for matched employees.
    Returns a summary dict.
    """
    results = {}

    try:
        results["daily"] = sync_daily_report(stats_response)
    except Exception as e:
        results["daily"] = {"success": False, "error": str(e)}
        print(f"[reports] Daily failed: {e}")

    try:
        payload  = stats_response.get("data", stats_response)
        members  = payload.get("members", [])
        results["employee"] = sync_employees(members)
    except Exception as e:
        results["employee"] = {"success": False, "error": str(e)}
        print(f"[reports] Employee failed: {e}")

    try:
        if attendance is not None:
            results["attendance"] = sync_attendance(attendance)
        else:
            results["attendance"] = {"success": False, "error": "No attendance data provided"}
    except Exception as e:
        results["attendance"] = {"success": False, "error": str(e)}
        print(f"[reports] Attendance failed: {e}")

    try:
        results["crm_comments"] = post_daily_crm_comments(stats_response)
    except Exception as e:
        results["crm_comments"] = {"success": False, "error": str(e)}
        print(f"[reports] CRM comments failed: {e}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Legacy sync_screenshots — unchanged for backwards compatibility
# ─────────────────────────────────────────────────────────────────────────────

def sync_screenshots(screenshots):
    date_str  = datetime.now(IST).strftime("%Y-%m-%d")
    now_str   = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    lines     = [f"WorkEye Screenshots Log", f"Date: {date_str}", f"Generated: {now_str} IST",
                 f"Total: {len(screenshots)}", ""]
    for i, s in enumerate(screenshots, 1):
        ts   = s.get("timestamp", "")
        name = s.get("member_name") or s.get("name", "—")
        lines.append(f"{i}. {name} | {ts[:10]} {ts[11:19] if len(ts)>10 else '—'} | {s.get('image_url','—')}")
    filename  = f"WorkEye_Screenshots_{date_str}.txt"
    encoded   = base64.b64encode("\n".join(lines).encode()).decode()
    folder_id = get_or_create_folder()
    if not folder_id:
        return {"success": False, "error": "Could not get folder"}
    result  = _call("disk.folder.uploadfile", {
        "id": folder_id, "data": {"NAME": filename}, "fileContent": encoded,
    })
    res     = result.get("result") or {}
    file_id = res.get("ID") if isinstance(res, dict) else None
    if not file_id:
        print(f"[Bitrix] Screenshots upload failed: {result.get('error', result)}")
    return {"success": bool(file_id), "file_id": file_id, "error": result.get("error")}
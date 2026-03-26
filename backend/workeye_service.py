import requests
from datetime import datetime, timedelta
import time


# =========================
# AUTH
# =========================
def get_token(base_url: str, email: str, password: str) -> dict:
    url = f"{base_url}/auth/admin/login"
    payload = {"email": email, "password": password}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    response = requests.post(url, json=payload, headers=headers, timeout=30)
    print(f"[LOGIN] Status: {response.status_code}")
    print(f"[LOGIN] Body: '{response.text[:300]}'")

    if not response.text.strip():
        raise Exception("WorkEye server returned empty response on login.")

    data = response.json()

    token_keys = ["token", "access_token", "auth_token", "authToken", "accessToken", "jwt"]
    token = next((data[k] for k in token_keys if data.get(k)), None)
    if not token:
        for val in data.values():
            if isinstance(val, dict):
                token = next((val[k] for k in token_keys if val.get(k)), None)
                if token:
                    break

    if not token:
        raise Exception(f"Login failed ({response.status_code}): {str(data)[:200]}")

    profile = {}
    for key in ["admin", "user", "profile", "account", "data"]:
        if isinstance(data.get(key), dict):
            profile = data[key]
            break
    for field in ["name", "full_name", "company_name", "company", "position", "role"]:
        if data.get(field) and not profile.get(field):
            profile[field] = data[field]

    print(f"[LOGIN] Success - profile keys: {list(profile.keys())}")
    return {"token": token, "profile": profile}


# =========================
# DASHBOARD STATS
# No per-member /live calls — stats endpoint already has all needed data
# =========================
def get_stats(base_url: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/api/dashboard/stats"

    try:
        r = requests.get(url, headers=headers, timeout=30)
    except requests.exceptions.Timeout:
        raise Exception("WorkEye backend timed out. It may be waking up — please wait 30s and try again.")

    if r.status_code == 401:
        raise Exception("Token expired. Please log in again.")
    if r.status_code == 503:
        raise Exception("WorkEye backend is sleeping. Please wait 30 seconds and refresh.")
    if r.status_code != 200:
        raise Exception(f"Stats failed: {r.status_code} - {r.text[:200]}")

    data = r.json()
    stats   = data.get("stats", {})
    members = data.get("members", [])

    # Try to enrich members with department from a dedicated members/users endpoint
    dept_map = _fetch_department_map(base_url, headers)
    if dept_map:
        for m in members:
            if not m.get("department"):
                mid = m.get("id")
                email = m.get("email", "")
                m["department"] = dept_map.get(mid) or dept_map.get(email) or None
        print(f"[stats] Enriched {sum(1 for m in members if m.get('department'))} members with department")

    total   = len(members)
    active  = sum(1 for m in members if (m.get("status") or "").lower() == "active")
    idle    = sum(1 for m in members if (m.get("status") or "").lower() == "idle")
    offline = total - active - idle
    all_prod = [m.get("productivity", 0) for m in members]
    avg_prod = int(sum(all_prod) / len(all_prod)) if all_prod else 0

    stats.update({
        "total_members": total, "active_now": active,
        "idle_now": idle, "offline": offline, "average_productivity": avg_prod,
    })

    print(f"[stats] Members:{total} Active:{active} Idle:{idle} Offline:{offline} Avg:{avg_prod}%")
    return {"stats": stats, "members": members}


def _fetch_department_map(base_url: str, headers: dict) -> dict:
    """
    Try several common endpoints to find department info.
    Returns a dict keyed by member id (int) and email (str) -> department name.
    """
    dept_map = {}
    candidate_urls = [
        f"{base_url}/api/members",
        f"{base_url}/api/users",
        f"{base_url}/api/employees",
        f"{base_url}/api/team",
        f"{base_url}/api/admin/members",
        f"{base_url}/api/admin/users",
        f"{base_url}/admin/members",
    ]
    for url in candidate_urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                continue
            raw = r.json()
            # Support {"members":[...]}, {"users":[...]}, {"data":[...]}, or a plain list
            items = (
                raw if isinstance(raw, list) else
                raw.get("members") or raw.get("users") or
                raw.get("employees") or raw.get("data") or []
            )
            if not items:
                continue
            print(f"[dept_map] Found {len(items)} items from {url}")
            for item in items:
                dept = (
                    item.get("department") or
                    item.get("department_name") or
                    item.get("dept") or
                    item.get("group") or
                    item.get("team") or
                    item.get("division") or
                    None
                )
                if dept:
                    if item.get("id"):
                        dept_map[item["id"]] = dept
                    if item.get("email"):
                        dept_map[item["email"]] = dept
            if dept_map:
                print(f"[dept_map] Built map with {len(dept_map)} entries from {url}")
                return dept_map
        except Exception as e:
            print(f"[dept_map] {url} failed: {e}")
            continue
    print("[dept_map] No department data found from any endpoint")
    return dept_map


# =========================
# MEMBER LIVE COUNTERS (only called when viewing individual member)
# =========================
def get_member_live(base_url: str, token: str, member_id: int) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        url = f"{base_url}/api/dashboard/member/{member_id}/live"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            counters = data.get("live_counters", {})
            member   = data.get("member", {})
            return {
                "screen_time":   counters.get("screen_time_seconds", 0),
                "active_time":   counters.get("active_time_seconds", 0),
                "idle_time":     counters.get("idle_time_seconds", 0),
                "productivity":  counters.get("productivity_percentage", 0),
                "status":        member.get("status"),
                "is_punched_in": member.get("is_punched_in", False),
            }
    except Exception as e:
        print(f"[live] Member {member_id} failed: {e}")
    return {}


# =========================
# ATTENDANCE
# =========================
def get_attendance(base_url: str, token: str, date: str = None) -> list:
    headers = {"Authorization": f"Bearer {token}"}

    try:
        url = f"{base_url}/api/attendance/members"
        params = {"date": date} if date else {}
        r = requests.get(url, headers=headers, params=params, timeout=20)

        if r.status_code == 200:
            data = r.json()
            print(f"[attendance] Raw keys: {list(data.keys())}")
            members = data.get("attendance") or data.get("members") or data.get("data") or []

            if members:
                result = []
                for m in members:
                    punch_in  = (m.get("punch_in_time") or m.get("punch_in") or
                                 m.get("check_in") or m.get("check_in_time") or None)
                    punch_out = (m.get("punch_out_time") or m.get("punch_out") or
                                 m.get("check_out") or m.get("check_out_time") or None)
                    today_hours = m.get("today_hours") or m.get("hours_worked") or 0
                    result.append({
                        "id":             m.get("id"),
                        "name":           m.get("name"),
                        "email":          m.get("email"),
                        "position":       m.get("position"),
                        "department":     m.get("department"),
                        "status":         m.get("status"),
                        "punch_in_time":  punch_in,
                        "punch_out_time": punch_out,
                        "today_hours":    round(float(today_hours or 0), 1),
                        "is_punched_in":  m.get("is_punched_in", False),
                    })
                return result

    except Exception as e:
        print(f"[attendance] Primary failed: {e}")

    # Fallback — derive from stats
    try:
        stats = get_stats(base_url, token)
        members = stats.get("members", [])
        return [{
            "id":             m.get("id"),
            "name":           m.get("name"),
            "email":          m.get("email"),
            "position":       m.get("position"),
            "department":     m.get("department"),
            "status":         m.get("status"),
            "punch_in_time":  None,
            "punch_out_time": None,
            "today_hours":    round((m.get("screen_time") or 0) / 3600, 1),
            "is_punched_in":  m.get("is_punched_in", False),
        } for m in members]
    except Exception:
        return []


# =========================
# ATTENDANCE MEMBER DETAIL
# =========================
def get_attendance_member(base_url: str, token: str, member_id: int,
                           start_date: str = None, end_date: str = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    params = {}
    if start_date: params["start_date"] = start_date
    if end_date:   params["end_date"]   = end_date

    url = f"{base_url}/api/attendance/member/{member_id}"
    r = requests.get(url, headers=headers, params=params, timeout=15)
    if r.status_code != 200:
        raise Exception(f"Attendance member failed: {r.status_code} - {r.text}")

    data = r.json()
    print(f"[attendance_member] Raw keys: {list(data.keys())}")

    # Grab daily records from whatever key the API uses
    records_raw = (
        data.get("daily_records") or
        data.get("attendance_records") or
        data.get("records") or
        data.get("attendance") or
        data.get("data") or
        []
    )

    def _extract_time(rec, *keys):
        """Return first non-empty value from any of the given keys."""
        for k in keys:
            v = rec.get(k)
            if v and str(v).strip() not in ("", "null", "None", "N/A"):
                return str(v).strip()
        return None

    def _calc_duration(punch_in, punch_out):
        if not punch_in or not punch_out:
            return ""
        try:
            def _parse(t):
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
                            "%Y-%m-%d %H:%M:%S", "%H:%M:%S", "%H:%M"):
                    try:
                        return datetime.strptime(t, fmt)
                    except ValueError:
                        continue
                return None
            dt_in  = _parse(punch_in)
            dt_out = _parse(punch_out)
            if dt_in and dt_out and dt_out > dt_in:
                total_minutes = int((dt_out - dt_in).total_seconds() / 60)
                return f"{total_minutes // 60}h {total_minutes % 60}m"
        except Exception:
            pass
        return ""

    normalized = []
    for rec in records_raw:
        print(f"[attendance_member] Record keys: {list(rec.keys())}")

        punch_in = _extract_time(
            rec,
            # All known field name variants WorkEye might use
            "punch_in_time", "punch_in", "check_in_time", "check_in",
            "login_time", "first_punch", "in_time", "start_time",
            "clockin_time", "clock_in", "clock_in_time", "time_in",
            "punchIn", "checkIn", "loginTime", "firstPunch",
        )
        punch_out = _extract_time(
            rec,
            "punch_out_time", "punch_out", "check_out_time", "check_out",
            "logout_time", "last_punch", "out_time", "end_time",
            "clockout_time", "clock_out", "clock_out_time", "time_out",
            "punchOut", "checkOut", "logoutTime", "lastPunch",
        )

        duration = (
            rec.get("duration") or
            rec.get("hours_worked") or
            rec.get("working_hours") or
            rec.get("total_hours") or
            _calc_duration(punch_in, punch_out) or
            ""
        )

        status = (
            rec.get("status") or
            rec.get("attendance_status") or
            ("Present" if punch_in else "Absent")
        )

        normalized.append({
            "date":           rec.get("date") or rec.get("attendance_date") or rec.get("day"),
            "punch_in_time":  punch_in,
            "punch_out_time": punch_out,
            "duration":       str(duration),
            "status":         status,
        })

    print(f"[attendance_member] Normalized {len(normalized)} records. "
          f"Sample punch_in: {normalized[0].get('punch_in_time') if normalized else 'N/A'}")

    # Preserve original response but replace daily_records with normalized data
    data["daily_records"] = normalized
    return data


# =========================
# CONFIGURATION
# =========================
def get_configuration(base_url: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/api/configuration"
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        raise Exception(f"Configuration failed: {r.status_code} - {r.text}")
    data = r.json()
    cfg = data.get("config") or data.get("configuration") or data.get("data") or data

    for key in ("office_start_time", "office_end_time"):
        val = cfg.get(key, "")
        if val and len(val) > 5:
            cfg[key] = val[:5]

    wd = cfg.get("working_days")
    if not isinstance(wd, list):
        cfg["working_days"] = [1, 2, 3, 4, 5]

    cfg["updated_at"] = cfg.get("last_modified_at") or cfg.get("updated_at")
    return cfg


# =========================
# ACTIVITY LOGS
# =========================
def get_activity_logs(base_url: str, token: str, member_id: int, date: str = None) -> list:
    headers = {"Authorization": f"Bearer {token}"}
    params = {}
    if date: params["date"] = date

    url = f"{base_url}/api/activity-logs/{member_id}"
    r = requests.get(url, headers=headers, params=params, timeout=15)
    if r.status_code != 200:
        raise Exception(f"Activity logs failed: {r.status_code} - {r.text}")
    data = r.json()
    return data.get("activities") or data.get("logs") or data.get("data") or []


# =========================
# ACTIVITY TRENDS
# =========================
def get_activity_trends(base_url: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/api/dashboard/activity-trends"
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        raise Exception(f"Trends failed: {r.status_code} - {r.text[:200]}")
    return r.json()


# =========================
# SCREENSHOTS
# =========================
def get_screenshots(base_url: str, token: str, date: str = None) -> list:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        stats = get_stats(base_url, token)
        members = stats.get("members", [])
    except Exception:
        return []

    all_screenshots = []
    for member in members:
        member_id   = member.get("id")
        member_name = member.get("name", "Unknown")
        if not member_id:
            continue
        try:
            url = f"{base_url}/api/screenshots/{member_id}"
            params = {"limit": 100, "offset": 0}
            if date:
                params.update({"date": date, "start_date": date, "end_date": date})
            r = requests.get(url, headers=headers, params=params, timeout=15)
            if r.status_code == 200:
                data = r.json()
                screenshots = data.get("screenshots") or []
                for s in screenshots:
                    s["member_name"]  = member_name
                    s["member_email"] = member.get("email", "")
                    s["image_url"] = (
                        s.get("screenshot_url") or
                        f"/proxy-image?workeye_url={base_url}&token={token}&screenshot_id={s['id']}"
                    )
                all_screenshots.extend(screenshots)
        except Exception as e:
            print(f"[screenshots] Member {member_id} failed: {e}")
            continue

    if date:
        all_screenshots = [s for s in all_screenshots if (s.get("timestamp") or "").startswith(date)]
    all_screenshots.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return all_screenshots


# =========================
# IMAGE FETCH
# =========================
# =========================
# ADMIN PROFILE
# =========================
def get_admin_profile(base_url: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    candidates = [
        f"{base_url}/api/admin/profile",
        f"{base_url}/api/admin/me",
        f"{base_url}/api/profile",
        f"{base_url}/api/me",
        f"{base_url}/auth/admin/profile",
        f"{base_url}/api/account",
        f"{base_url}/api/admin/account",
        f"{base_url}/api/settings/profile",
        f"{base_url}/api/admin/settings",
    ]
    for url in candidates:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                profile = data.get("admin") or data.get("user") or data.get("profile") or data.get("data") or data
                if isinstance(profile, dict) and (profile.get("name") or profile.get("email") or profile.get("company_name")):
                    print(f"[profile] Found profile at {url}")
                    return profile
        except Exception:
            continue
    print("[profile] No profile endpoint found")
    return {}


def get_screenshot_image(base_url: str, token: str, screenshot_id: int) -> bytes:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/api/screenshots/image/{screenshot_id}"
    r = requests.get(url, headers=headers, timeout=15)
    print(f"[image] Status: {r.status_code} id:{screenshot_id}")
    if r.status_code != 200:
        raise Exception(f"Image failed: {r.status_code} - {r.text[:100]}")
    return r.content
import requests
from datetime import datetime, timedelta


# =========================
# AUTH
# =========================
def get_token(base_url: str, email: str, password: str) -> str:
    """
    WorkEye admin login endpoint: POST /auth/admin/login
    Returns: { token, refresh_token, admin: {...} }
    """
    endpoints = [
        "/auth/admin/login",
        "/auth/login",
        "/api/auth/login"
    ]

    payload = {"email": email, "password": password}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    for ep in endpoints:
        url = f"{base_url}{ep}"
        try:
            print(f"[LOGIN] Trying: {url}")
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            print(f"[LOGIN] Status: {response.status_code}")
            print(f"[LOGIN] Raw Response: '{response.text[:200]}'")

            if not response.text.strip():
                print("[LOGIN] Empty response → likely wrong endpoint")
                continue

            try:
                data = response.json()
            except Exception:
                print("[LOGIN] Not JSON → probably HTML response")
                continue

            token = data.get("token") or data.get("access_token")

            if token:
                print("[LOGIN] ✅ Success")
                return token
            else:
                print("[LOGIN] Token missing")

        except Exception as e:
            print(f"[LOGIN] Error: {e}")

    raise Exception("Login failed: API not returning valid JSON/token")


# =========================
# MEMBER LIVE COUNTERS
# Endpoint: GET /api/dashboard/member/<member_id>/live
# Response: { success, member: {...}, live_counters: { screen_time_seconds,
#             active_time_seconds, idle_time_seconds, productivity_percentage, ... } }
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
            # Normalise keys to match what get_stats() expects
            return {
                "screen_time":   counters.get("screen_time_seconds", 0),
                "active_time":   counters.get("active_time_seconds", 0),
                "idle_time":     counters.get("idle_time_seconds", 0),
                "productivity":  counters.get("productivity_percentage", 0),
                "status":        member.get("status"),
                "is_punched_in": member.get("is_punched_in", False),
            }
        else:
            print(f"[live] Member {member_id} → HTTP {r.status_code}")
    except Exception as e:
        print(f"[live] Member {member_id} failed: {e}")
    return {}


# =========================
# DASHBOARD STATS
# Endpoint: GET /api/dashboard/stats
# Response: { success, stats: { total_members, active_now, idle_now, offline,
#             average_productivity }, members: [...], date, timestamp }
# =========================
def get_stats(base_url: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/api/dashboard/stats"

    r = requests.get(url, headers=headers, timeout=15)

    if r.status_code != 200:
        raise Exception(f"Stats failed: {r.status_code} - {r.text}")

    data = r.json()

    # WorkEye returns { success, stats: {...}, members: [...] }
    stats   = data.get("stats", {})
    members = data.get("members", [])

    # Enrich each member with live counters
    enriched = []
    for m in members:
        member_id = m.get("id")
        if member_id:
            live = get_member_live(base_url, token, member_id)
            if live:
                m.update({
                    "screen_time":   live.get("screen_time",   m.get("screen_time", 0)),
                    "active_time":   live.get("active_time",   m.get("active_time", 0)),
                    "idle_time":     live.get("idle_time",     m.get("idle_time", 0)),
                    "productivity":  live.get("productivity",  m.get("productivity", 0)),
                    "status":        live.get("status") or m.get("status"),
                    "is_punched_in": live.get("is_punched_in", m.get("is_punched_in", False)),
                })
        # Normalize department field — WorkEye may use different key names
        m["department"] = (
            m.get("department") or
            m.get("department_name") or
            m.get("dept") or
            m.get("dept_name") or
            m.get("team") or
            m.get("team_name") or
            m.get("group") or
            m.get("group_name") or
            None
        )
        enriched.append(m)

    # Recalculate aggregate counts from enriched data (live statuses may differ)
    total   = len(enriched)
    active  = sum(1 for m in enriched if (m.get("status") or "").lower() == "active")
    idle    = sum(1 for m in enriched if (m.get("status") or "").lower() == "idle")
    offline = total - active - idle

    all_prod = [m.get("productivity", 0) for m in enriched]
    avg_prod = int(sum(all_prod) / len(all_prod)) if all_prod else 0

    stats.update({
        "total_members":        total,
        "active_now":           active,
        "idle_now":             idle,
        "offline":              offline,
        "average_productivity": avg_prod,
    })

    print(f"[stats] Members:{total} Active:{active} Idle:{idle} Offline:{offline} Avg:{avg_prod}%")

    return {"stats": stats, "members": enriched}


# =========================
# ACTIVITY TRENDS (7-day chart)
# Endpoint: GET /api/dashboard/activity-trends
# =========================
def get_activity_trends(base_url: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/api/dashboard/activity-trends"
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        raise Exception(f"Trends failed: {r.status_code} - {r.text}")
    return r.json()


# =========================
# ATTENDANCE (members list)
# Endpoint: GET /api/attendance/members
# Response: { success, attendance: [...] }
# =========================
def get_attendance(base_url: str, token: str, date: str = None) -> list:
    headers = {"Authorization": f"Bearer {token}"}

    try:
        url = f"{base_url}/api/attendance/members"
        params = {"date": date} if date else {}

        r = requests.get(url, headers=headers, params=params, timeout=15)

        if r.status_code == 200:
            data = r.json()
            # WorkEye returns key 'attendance', fallback to 'members' / 'data'
            members = (
                data.get("attendance")
                or data.get("members")
                or data.get("data")
                or []
            )
            if members:
                return members

    except Exception as e:
        print(f"[attendance] Primary failed: {e}")

    # Fallback — derive attendance from stats
    try:
        stats = get_stats(base_url, token)
        members = stats.get("members", [])
        return [{
            "name":          m.get("name"),
            "email":         m.get("email"),
            "position":      m.get("position"),
            "status":        m.get("status"),
            "today_hours":   round((m.get("screen_time") or 0) / 3600, 1),
            "is_punched_in": m.get("is_punched_in", False),
        } for m in members]
    except Exception:
        return []


# =========================
# ATTENDANCE MEMBER DETAIL
# Endpoint: GET /api/attendance/member/<member_id>
# Response: { success, member, statistics, daily_records }
# =========================
def get_attendance_member(base_url: str, token: str, member_id: int,
                           start_date: str = None, end_date: str = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    params = {}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    url = f"{base_url}/api/attendance/member/{member_id}"
    r = requests.get(url, headers=headers, params=params, timeout=15)

    if r.status_code != 200:
        raise Exception(f"Attendance member failed: {r.status_code} - {r.text}")

    return r.json()


# =========================
# CONFIGURATION
# Endpoint: GET /api/configuration
# Response: { success, configuration: {...} }
# =========================
def get_configuration(base_url: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/api/configuration"
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        raise Exception(f"Configuration failed: {r.status_code} - {r.text}")
    data = r.json()

    # WorkEye returns: { success, config: { id, company_id, screenshot_interval_minutes,
    #   idle_timeout_minutes, office_start_time, office_end_time, working_days,
    #   last_modified_by, last_modified_at, created_at } }
    cfg = data.get("config") or data.get("configuration") or data.get("data") or data

    # office_start_time and office_end_time come as "HH:MM:SS" — trim to "HH:MM"
    for key in ("office_start_time", "office_end_time"):
        val = cfg.get(key, "")
        if val and len(val) > 5:
            cfg[key] = val[:5]  # "09:00:00" → "09:00"

    # working_days is JSONB list of ints [1,2,3,4,5] already — just ensure it's a list
    wd = cfg.get("working_days")
    if not isinstance(wd, list):
        cfg["working_days"] = [1, 2, 3, 4, 5]

    # Map last_modified_at → updated_at (what frontend uses)
    cfg["updated_at"] = cfg.get("last_modified_at") or cfg.get("updated_at")

    return cfg


# =========================
# ACTIVITY LOGS
# Endpoint: GET /api/activity-logs/<member_id>
# Response: { success, member, activities: [...], pagination, date }
# =========================
def get_activity_logs(base_url: str, token: str, member_id: int, date: str = None) -> list:
    headers = {"Authorization": f"Bearer {token}"}
    params = {}
    if date:
        params["date"] = date

    url = f"{base_url}/api/activity-logs/{member_id}"
    r = requests.get(url, headers=headers, params=params, timeout=15)

    if r.status_code != 200:
        raise Exception(f"Activity logs failed: {r.status_code} - {r.text}")

    data = r.json()
    # WorkEye returns key 'activities'
    return data.get("activities") or data.get("logs") or data.get("data") or []


# =========================
# SCREENSHOTS
# Endpoint: GET /api/screenshots/<member_id>
# Response: { success, screenshots: [...] }
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
        member_id = member.get("id")
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
                # WorkEye returns key 'screenshots'
                screenshots = data.get("screenshots") or []
                for s in screenshots:
                    s["image_url"] = (
                        s.get("screenshot_url")
                        or f"/proxy-image?screenshot_id={s['id']}"
                    )
                    all_screenshots.append(s)

        except Exception as e:
            print(f"[screenshots] Member {member_id} failed: {e}")

    return all_screenshots


# =========================
# IMAGE FETCH
# Endpoint: GET /api/screenshots/image/<screenshot_id>
# =========================
def get_screenshot_image(base_url: str, token: str, screenshot_id: int) -> bytes:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/api/screenshots/image/{screenshot_id}"

    r = requests.get(url, headers=headers, timeout=15)
    print(f"[image] Status: {r.status_code} id:{screenshot_id}")

    if r.status_code != 200:
        raise Exception(f"Image failed: {r.status_code} - {r.text[:100]}")

    return r.content
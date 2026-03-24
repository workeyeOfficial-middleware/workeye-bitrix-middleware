import requests
from datetime import datetime, timedelta


# =========================
# AUTH
# =========================
def get_token(base_url: str, email: str, password: str) -> str:
    endpoints = [
        "/auth/admin/login",
        "/auth/login",
        "/api/auth/login"
    ]
    payload = {"email": email, "password": password}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    for ep in endpoints:
        url = f"{base_url}{ep}"
        try:
            print(f"[LOGIN] Trying: {url}")
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            print(f"[LOGIN] Status: {response.status_code}")
            print(f"[LOGIN] Raw Response: '{response.text[:300]}'")

            if not response.text.strip():
                print("[LOGIN] Empty response → wrong endpoint")
                continue

            try:
                data = response.json()
            except Exception:
                print("[LOGIN] Not JSON → probably HTML")
                continue

            # Try every possible token key
            token = (
                data.get("token") or
                data.get("access_token") or
                data.get("auth_token") or
                data.get("authToken") or
                data.get("accessToken") or
                data.get("jwt")
            )
            # Try nested
            if not token and isinstance(data.get("data"), dict):
                token = data["data"].get("token") or data["data"].get("access_token")
            if not token and isinstance(data.get("result"), dict):
                token = data["result"].get("token")
            if not token and isinstance(data.get("user"), dict):
                token = data["user"].get("token")

            if token:
                print("[LOGIN] ✅ Success")
                return token
            else:
                print(f"[LOGIN] Token missing. Keys: {list(data.keys())}")

        except Exception as e:
            print(f"[LOGIN] Error: {e}")

    raise Exception("Login failed: No valid token returned from WorkEye API")


# =========================
# MEMBER LIVE COUNTERS
# =========================
def get_member_live(base_url: str, token: str, member_id: int) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        url = f"{base_url}/api/dashboard/member/{member_id}/live"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            counters = data.get("live_counters", {})
            member = data.get("member", {})
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
# =========================
def get_stats(base_url: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/api/dashboard/stats"
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        raise Exception(f"Stats failed: {r.status_code} - {r.text}")

    data = r.json()
    stats   = data.get("stats", {})
    members = data.get("members", [])

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
        m["department"] = (
            m.get("department") or m.get("department_name") or
            m.get("dept") or m.get("team") or m.get("group") or None
        )
        enriched.append(m)

    total   = len(enriched)
    active  = sum(1 for m in enriched if (m.get("status") or "").lower() == "active")
    idle    = sum(1 for m in enriched if (m.get("status") or "").lower() == "idle")
    offline = total - active - idle
    all_prod = [m.get("productivity", 0) for m in enriched]
    avg_prod = int(sum(all_prod) / len(all_prod)) if all_prod else 0

    stats.update({
        "total_members": total, "active_now": active,
        "idle_now": idle, "offline": offline, "average_productivity": avg_prod,
    })
    print(f"[stats] Members:{total} Active:{active} Idle:{idle} Offline:{offline} Avg:{avg_prod}%")
    return {"stats": stats, "members": enriched}


# =========================
# ATTENDANCE — with punch times
# =========================
def get_attendance(base_url: str, token: str, date: str = None) -> list:
    headers = {"Authorization": f"Bearer {token}"}

    try:
        url = f"{base_url}/api/attendance/members"
        params = {"date": date} if date else {}
        r = requests.get(url, headers=headers, params=params, timeout=15)

        if r.status_code == 200:
            data = r.json()
            print(f"[attendance] Raw keys: {list(data.keys())}")

            # WorkEye returns key 'attendance', 'members', or 'data'
            members = (
                data.get("attendance") or
                data.get("members") or
                data.get("data") or
                []
            )

            if members:
                # Normalize punch times — try multiple possible key names
                result = []
                for m in members:
                    punch_in  = (
                        m.get("punch_in_time") or
                        m.get("punch_in") or
                        m.get("check_in") or
                        m.get("check_in_time") or
                        m.get("in_time") or
                        m.get("login_time") or
                        None
                    )
                    punch_out = (
                        m.get("punch_out_time") or
                        m.get("punch_out") or
                        m.get("check_out") or
                        m.get("check_out_time") or
                        m.get("out_time") or
                        m.get("logout_time") or
                        None
                    )
                    is_punched_in = m.get("is_punched_in", False)
                    today_hours   = m.get("today_hours") or m.get("hours_worked") or m.get("total_hours") or 0

                    print(f"[attendance] Member: {m.get('name')} | punch_in: {punch_in} | punch_out: {punch_out} | keys: {list(m.keys())[:10]}")

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
                        "is_punched_in":  is_punched_in,
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
    inner = data.get("data") or data

    records = inner.get("daily_records") or inner.get("records") or []

    cleaned = []

    for rec in records:
        punch_in = (
            rec.get("punch_in_time") or
            rec.get("punch_in") or
            rec.get("check_in") or
            rec.get("check_in_time") or
            rec.get("in_time") or
            rec.get("login_time")
        )

        punch_out = (
            rec.get("punch_out_time") or
            rec.get("punch_out") or
            rec.get("check_out") or
            rec.get("check_out_time") or
            rec.get("out_time") or
            rec.get("logout_time")
        )

        duration = rec.get("duration") or rec.get("hours") or rec.get("total_hours") or 0

        # ✅ Decide status ONLY from real data
        if punch_in:
            status = "Present"
        elif rec.get("status"):
            status = rec.get("status")
        else:
            status = "Absent"

        cleaned.append({
            "date": rec.get("date"),
            "punch_in_time": punch_in,
            "punch_out_time": punch_out,
            "hours": duration,
            "status": status
        })

        print(f"[DETAIL] {rec.get('date')} | in:{punch_in} | out:{punch_out}")

    return {
        "records": cleaned
    }

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
def get_screenshot_image(base_url: str, token: str, screenshot_id: int) -> bytes:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/api/screenshots/image/{screenshot_id}"
    r = requests.get(url, headers=headers, timeout=15)
    print(f"[image] Status: {r.status_code} id:{screenshot_id}")
    if r.status_code != 200:
        raise Exception(f"Image failed: {r.status_code} - {r.text[:100]}")
    return r.content
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed


# =========================
# AUTH
# =========================
def get_token(base_url: str, email: str, password: str) -> str:
    endpoints = ["/auth/admin/login", "/auth/login", "/api/auth/login"]
    payload = {"email": email, "password": password}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    for ep in endpoints:
        url = f"{base_url}{ep}"
        try:
            print(f"[LOGIN] Trying: {url}")
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            print(f"[LOGIN] Status: {response.status_code}")
            print(f"[LOGIN] Raw: '{response.text[:300]}'")

            if not response.text.strip():
                continue
            try:
                data = response.json()
            except Exception:
                continue

            token = (
                data.get("token") or data.get("access_token") or
                data.get("auth_token") or data.get("authToken") or
                data.get("accessToken") or data.get("jwt")
            )
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
# FETCH TODAY'S PUNCH TIMES FOR ONE MEMBER
# Uses /api/attendance/member/{id} with today's date
# =========================
def _fetch_member_punch(base_url: str, token: str, member: dict) -> dict:
    """Fetch today's punch in/out for a single member and merge into their dict."""
    member_id = member.get("id")
    if not member_id:
        return member

    today = datetime.now().strftime("%Y-%m-%d")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        url = f"{base_url}/api/attendance/member/{member_id}"
        params = {"start_date": today, "end_date": today}
        r = requests.get(url, headers=headers, params=params, timeout=10)

        if r.status_code == 200:
            data = r.json()
            # The response shape: { data: { daily_records: [...], statistics: {...} } }
            inner = data.get("data") or data
            records = inner.get("daily_records") or inner.get("records") or []

            # Find today's record
            today_record = None
            for rec in records:
                if rec.get("date") == today:
                    today_record = rec
                    break
            # Fallback: use first record if only one
            if not today_record and len(records) == 1:
                today_record = records[0]

            if today_record:
                punch_in  = today_record.get("punch_in_time") or today_record.get("punch_in") or today_record.get("in_time")
                punch_out = today_record.get("punch_out_time") or today_record.get("punch_out") or today_record.get("out_time")
                hours     = today_record.get("duration") or today_record.get("hours") or today_record.get("total_hours") or 0

                member["punch_in_time"]  = punch_in
                member["punch_out_time"] = punch_out
                member["today_hours"]    = _parse_duration_to_hours(hours)
                member["is_punched_in"]  = punch_in is not None and punch_out is None

                print(f"[attendance] {member.get('name')} | in:{punch_in} | out:{punch_out}")
            else:
                member.setdefault("punch_in_time",  None)
                member.setdefault("punch_out_time", None)
                member.setdefault("today_hours",    0)
        else:
            print(f"[attendance] Member {member_id} → HTTP {r.status_code}")
            member.setdefault("punch_in_time",  None)
            member.setdefault("punch_out_time", None)
            member.setdefault("today_hours",    0)

    except Exception as e:
        print(f"[attendance] Member {member_id} fetch failed: {e}")
        member.setdefault("punch_in_time",  None)
        member.setdefault("punch_out_time", None)
        member.setdefault("today_hours",    0)

    return member


def _parse_duration_to_hours(duration) -> float:
    """Parse '4h 17m' or '4:17:00' or seconds int to float hours."""
    if not duration:
        return 0.0
    if isinstance(duration, (int, float)):
        return round(float(duration) / 3600, 1) if float(duration) > 100 else round(float(duration), 1)
    s = str(duration)
    # "4h 17m" format
    import re
    hm = re.match(r'(\d+)h\s*(\d*)m?', s)
    if hm:
        return round(int(hm.group(1)) + int(hm.group(2) or 0) / 60, 1)
    # "4:17:00" format
    colon = re.match(r'(\d+):(\d+):(\d+)', s)
    if colon:
        return round(int(colon.group(1)) + int(colon.group(2)) / 60, 1)
    return 0.0


# =========================
# ATTENDANCE LIST — fetches punch times per member
# =========================
def get_attendance(base_url: str, token: str, date: str = None) -> list:
    headers_req = {"Authorization": f"Bearer {token}"}

    # Step 1: Try /api/attendance/members for the list
    members_list = []
    try:
        url = f"{base_url}/api/attendance/members"
        params = {"date": date} if date else {}
        r = requests.get(url, headers=headers_req, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            print(f"[attendance/members] Keys: {list(data.keys())}")
            members_list = (
                data.get("attendance") or
                data.get("members") or
                data.get("data") or
                []
            )
    except Exception as e:
        print(f"[attendance/members] Failed: {e}")

    # Step 2: If no list, fall back to stats members
    if not members_list:
        try:
            stats = get_stats(base_url, token)
            members_list = stats.get("members", [])
        except Exception as e:
            print(f"[attendance] Stats fallback failed: {e}")
            return []

    # Step 3: For each member, fetch today's punch times individually
    # Use threads for speed (parallel requests)
    result = []
    target_date = date or datetime.now().strftime("%Y-%m-%d")

    def fetch_one(m):
        mid = m.get("id")
        if not mid:
            m.setdefault("punch_in_time", None)
            m.setdefault("punch_out_time", None)
            m.setdefault("today_hours", 0)
            return m
        try:
            url = f"{base_url}/api/attendance/member/{mid}"
            params = {"start_date": target_date, "end_date": target_date}
            r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=10)
            if r.status_code == 200:
                data = r.json()
                inner = data.get("data") or data
                records = inner.get("daily_records") or inner.get("records") or []

                today_rec = next((rec for rec in records if rec.get("date") == target_date), None)
                if not today_rec and len(records) == 1:
                    today_rec = records[0]

                if today_rec:
                    punch_in  = (today_rec.get("punch_in_time") or today_rec.get("punch_in") or today_rec.get("in_time"))
                    punch_out = (today_rec.get("punch_out_time") or today_rec.get("punch_out") or today_rec.get("out_time"))
                    dur       = today_rec.get("duration") or today_rec.get("hours") or 0
                    m["punch_in_time"]  = punch_in
                    m["punch_out_time"] = punch_out
                    m["today_hours"]    = _parse_duration_to_hours(dur)
                    m["is_punched_in"]  = bool(punch_in and not punch_out)
                    print(f"[att] {m.get('name')} in={punch_in} out={punch_out}")
                else:
                    m.setdefault("punch_in_time", None)
                    m.setdefault("punch_out_time", None)
                    m.setdefault("today_hours", 0)
        except Exception as e:
            print(f"[att] Member {mid} error: {e}")
            m.setdefault("punch_in_time", None)
            m.setdefault("punch_out_time", None)
            m.setdefault("today_hours", 0)
        return m

    # Parallel fetch — up to 10 at a time
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_one, m): m for m in members_list}
        for future in as_completed(futures):
            try:
                result.append(future.result())
            except Exception:
                result.append(futures[future])

    # Sort by name for consistent display
    result.sort(key=lambda x: (x.get("name") or "").lower())
    return result


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
    return r.json()


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
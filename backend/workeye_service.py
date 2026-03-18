import requests
from datetime import datetime, timedelta

def get_token(base_url: str, email: str, password: str) -> str:
    url = f"{base_url}/auth/admin/login"
    payload = {"email": email, "password": password}
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=payload, headers=headers, timeout=15)
    print("Login Status:", response.status_code)
    if response.status_code != 200:
        raise Exception("Invalid email or password")
    data = response.json()
    token = data.get("token") or data.get("access_token")
    if not token:
        raise Exception("Token not found in response")
    return token


def get_member_live(base_url: str, token: str, member_id: int) -> dict:
    """
    Fetch live counters for a single member.
    Returns accurate real-time productivity, screen time, active time, idle time.
    Falls back to empty dict if the call fails.
    """
    try:
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{base_url}/api/dashboard/member/{member_id}/live"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            counters = data.get("live_counters") or {}
            member_info = data.get("member") or {}
            return {
                "screen_time":   counters.get("screen_time_seconds", 0),
                "active_time":   counters.get("active_time_seconds", 0),
                "idle_time":     counters.get("idle_time_seconds", 0),
                "productivity":  counters.get("productivity_percentage", 0),
                "status":        member_info.get("status"),
                "is_punched_in": member_info.get("is_punched_in", False),
            }
    except Exception as e:
        print(f"[live] Failed for member {member_id}: {e}")
    return {}


def get_stats(base_url: str, token: str) -> dict:
    """
    Fetch dashboard stats and enrich each member with live productivity data.
    Uses /api/dashboard/stats for the member list, then calls
    /api/dashboard/member/:id/live for accurate per-member figures.
    """
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/api/dashboard/stats"
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        raise Exception(f"Failed to fetch stats: {r.status_code}")

    data = r.json()
    payload  = data.get("data") or data
    stats    = payload.get("stats") or payload
    members  = payload.get("members") or []

    # Enrich every member with live data
    enriched = []
    for m in members:
        member_id = m.get("id")
        if member_id:
            live = get_member_live(base_url, token, member_id)
            if live:
                m["screen_time"]   = live.get("screen_time",  m.get("screen_time", 0))
                m["active_time"]   = live.get("active_time",  m.get("active_time", 0))
                m["idle_time"]     = live.get("idle_time",    m.get("idle_time", 0))
                m["productivity"]  = live.get("productivity", m.get("productivity", 0))
                if live.get("status"):
                    m["status"] = live["status"]
                m["is_punched_in"] = live.get("is_punched_in", m.get("is_punched_in", False))
        enriched.append(m)

    # Recalculate aggregate stats from enriched members
    total   = len(enriched)
    active  = sum(1 for m in enriched if (m.get("status") or "").lower() == "active")
    idle    = sum(1 for m in enriched if (m.get("status") or "").lower() == "idle")
    offline = sum(1 for m in enriched if (m.get("status") or "").lower() == "offline")

    all_prod = [m.get("productivity", 0) for m in enriched]
    avg_prod = int(sum(all_prod) / len(all_prod)) if all_prod else 0

    stats["total_members"]        = total
    stats["active_now"]           = active
    stats["idle_now"]             = idle
    stats["offline"]              = offline
    stats["average_productivity"] = avg_prod

    print(f"[stats] {total} members | Active:{active} Idle:{idle} Offline:{offline} AvgProd:{avg_prod}%")

    return {"stats": stats, "members": enriched}


def get_attendance(base_url: str, token: str, date: str = None) -> list:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        url = f"{base_url}/api/attendance/members"
        params = {}
        if date:
            params["date"] = date
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            members = data.get("members") or data.get("data") or []
            if members:
                return members
    except:
        pass
    try:
        stats = get_stats(base_url, token)
        members = stats.get("members", [])
        return [{
            "name":           m.get("name"),
            "email":          m.get("email"),
            "position":       m.get("position"),
            "status":         m.get("status"),
            "punch_in_time":  None,
            "punch_out_time": None,
            "today_hours":    round((m.get("screen_time") or 0) / 3600, 1),
            "is_punched_in":  m.get("is_punched_in", False)
        } for m in members]
    except:
        return []


def get_screenshots(base_url: str, token: str, date: str = None) -> list:
    """Fetch ALL screenshots for all members across all dates"""
    headers = {"Authorization": f"Bearer {token}"}

    try:
        stats = get_stats(base_url, token)
        members = stats.get("members", [])
    except:
        return []

    all_screenshots = []

    for member in members:
        member_id    = member.get("id")
        member_name  = member.get("name", "Unknown")
        member_email = member.get("email", "")
        if not member_id:
            continue

        try:
            params = {"limit": 100, "offset": 0}
            if date:
                params["date"] = date

            url = f"{base_url}/api/screenshots/{member_id}"
            r = requests.get(url, headers=headers, params=params, timeout=15)

            if r.status_code == 200:
                data        = r.json()
                screenshots = data.get("screenshots") or []
                total       = data.get("pagination", {}).get("total", 0)

                offset = 100
                while len(screenshots) < total and offset < total:
                    params["offset"] = offset
                    r2 = requests.get(url, headers=headers, params=params, timeout=15)
                    if r2.status_code == 200:
                        more = r2.json().get("screenshots") or []
                        if not more:
                            break
                        screenshots.extend(more)
                    offset += 100

                for s in screenshots:
                    s["member_name"]  = member_name
                    s["member_email"] = member_email
                    # Use Cloudinary URL directly if available, else fallback to proxy
                    if s.get("screenshot_url"):
                        s["image_url"] = s["screenshot_url"]
                    else:
                        s["image_url"] = f"/proxy-image?workeye_url={base_url}&token={token}&screenshot_id={s['id']}"

                all_screenshots.extend(screenshots)

        except Exception as e:
            print(f"Failed to get screenshots for member {member_id}: {e}")
            continue

    all_screenshots.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return all_screenshots


def get_screenshot_image(base_url: str, token: str, screenshot_id: int) -> bytes:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/api/screenshots/image/{screenshot_id}"
    r = requests.get(url, headers=headers, timeout=15)
    print(f"Image fetch status: {r.status_code} for id {screenshot_id}")
    if r.status_code != 200:
        raise Exception(f"Image not found: {r.status_code} - {r.text[:100]}")
    return r.content

def get_configuration(base_url: str, token: str) -> dict:
    """Fetch admin configuration settings"""
    try:
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{base_url}/api/configuration"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get("config") or data
    except Exception as e:
        print(f"[config] Failed: {e}")
    return {}


def get_attendance_member(base_url: str, token: str, member_id: int, start_date: str = None, end_date: str = None) -> dict:
    try:
        headers = {"Authorization": f"Bearer {token}"}
        params = {}
        if start_date: params["start_date"] = start_date
        if end_date: params["end_date"] = end_date
        url = f"{base_url}/api/attendance/member/{member_id}"
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"[attendance_member] Failed: {e}")
    return {}
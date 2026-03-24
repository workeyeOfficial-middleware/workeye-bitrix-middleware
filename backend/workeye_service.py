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
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"  # 🔥 IMPORTANT FIX
    }

    for ep in endpoints:
        url = f"{base_url}{ep}"
        try:
            print(f"[LOGIN] Trying: {url}")

            response = requests.post(url, json=payload, headers=headers, timeout=15)

            print(f"[LOGIN] Status: {response.status_code}")
            print(f"[LOGIN] Raw Response: '{response.text[:200]}'")

            # 🔥 FIX: handle empty response
            if not response.text.strip():
                print("[LOGIN] Empty response → likely wrong endpoint")
                continue

            # 🔥 SAFE JSON PARSE
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
# DASHBOARD STATS
# =========================
def get_stats(base_url: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/api/dashboard/stats"

    r = requests.get(url, headers=headers, timeout=15)

    if r.status_code != 200:
        raise Exception(f"Stats failed: {r.status_code} - {r.text}")

    data = r.json()
    payload = data.get("data") or data
    stats = payload.get("stats") or payload
    members = payload.get("members") or []

    enriched = []

    for m in members:
        member_id = m.get("id")

        if member_id:
            live = get_member_live(base_url, token, member_id)

            if live:
                m.update({
                    "screen_time": live.get("screen_time", m.get("screen_time", 0)),
                    "active_time": live.get("active_time", m.get("active_time", 0)),
                    "idle_time": live.get("idle_time", m.get("idle_time", 0)),
                    "productivity": live.get("productivity", m.get("productivity", 0)),
                    "status": live.get("status") or m.get("status"),
                    "is_punched_in": live.get("is_punched_in", m.get("is_punched_in", False)),
                })

        enriched.append(m)

    total = len(enriched)
    active = sum(1 for m in enriched if (m.get("status") or "").lower() == "active")
    idle = sum(1 for m in enriched if (m.get("status") or "").lower() == "idle")
    offline = sum(1 for m in enriched if (m.get("status") or "").lower() == "offline")

    all_prod = [m.get("productivity", 0) for m in enriched]
    avg_prod = int(sum(all_prod) / len(all_prod)) if all_prod else 0

    stats.update({
        "total_members": total,
        "active_now": active,
        "idle_now": idle,
        "offline": offline,
        "average_productivity": avg_prod
    })

    print(f"[stats] Members:{total} Active:{active} Idle:{idle} Offline:{offline} Avg:{avg_prod}%")

    return {"stats": stats, "members": enriched}


# =========================
# ATTENDANCE
# =========================
def get_attendance(base_url: str, token: str, date: str = None) -> list:
    headers = {"Authorization": f"Bearer {token}"}

    try:
        url = f"{base_url}/api/attendance/members"
        params = {"date": date} if date else {}

        r = requests.get(url, headers=headers, params=params, timeout=15)

        if r.status_code == 200:
            data = r.json()
            members = data.get("members") or data.get("data") or []

            if members:
                return members

    except Exception as e:
        print(f"[attendance] Primary failed: {e}")

    # fallback
    try:
        stats = get_stats(base_url, token)
        members = stats.get("members", [])

        return [{
            "name": m.get("name"),
            "email": m.get("email"),
            "position": m.get("position"),
            "status": m.get("status"),
            "today_hours": round((m.get("screen_time") or 0) / 3600, 1),
            "is_punched_in": m.get("is_punched_in", False)
        } for m in members]

    except:
        return []


# =========================
# SCREENSHOTS
# =========================
def get_screenshots(base_url: str, token: str, date: str = None) -> list:
    headers = {"Authorization": f"Bearer {token}"}

    try:
        stats = get_stats(base_url, token)
        members = stats.get("members", [])
    except:
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
                params.update({
                    "date": date,
                    "start_date": date,
                    "end_date": date
                })

            r = requests.get(url, headers=headers, params=params, timeout=15)

            if r.status_code == 200:
                data = r.json()
                screenshots = data.get("screenshots") or []

                for s in screenshots:
                    s["image_url"] = s.get("screenshot_url") or f"/proxy-image?screenshot_id={s['id']}"
                    all_screenshots.append(s)

        except Exception as e:
            print(f"[screenshots] Member {member_id} failed: {e}")

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
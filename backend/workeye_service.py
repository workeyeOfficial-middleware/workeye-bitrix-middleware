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

def get_stats(base_url: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/api/dashboard/stats"
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        raise Exception(f"Failed to fetch stats: {r.status_code}")
    data = r.json()
    payload = data.get("data") or data
    stats = payload.get("stats") or payload
    members = payload.get("members") or []
    return {"stats": stats, "members": members}

def get_attendance(base_url: str, token: str) -> list:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        url = f"{base_url}/api/attendance/members"
        r = requests.get(url, headers=headers, timeout=15)
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
            "name": m.get("name"),
            "email": m.get("email"),
            "position": m.get("position"),
            "status": m.get("status"),
            "punch_in_time": None,
            "punch_out_time": None,
            "today_hours": round((m.get("screen_time") or 0) / 3600, 1),
            "is_punched_in": m.get("is_punched_in", False)
        } for m in members]
    except:
        return []

def get_screenshots(base_url: str, token: str, date: str = None) -> list:
    """Fetch ALL screenshots for all members across all dates"""
    headers = {"Authorization": f"Bearer {token}"}

    # Get all members first
    try:
        stats = get_stats(base_url, token)
        members = stats.get("members", [])
    except:
        return []

    all_screenshots = []

    for member in members:
        member_id = member.get("id")
        member_name = member.get("name", "Unknown")
        member_email = member.get("email", "")
        if not member_id:
            continue

        # Fetch last 30 days of screenshots per member
        try:
            # Use large limit and no date filter to get all screenshots
            params = {"limit": 100, "offset": 0}
            if date:
                params["date"] = date

            url = f"{base_url}/api/screenshots/{member_id}"
            r = requests.get(url, headers=headers, params=params, timeout=15)

            if r.status_code == 200:
                data = r.json()
                screenshots = data.get("screenshots") or []
                total = data.get("pagination", {}).get("total", 0)

                # If there are more pages, fetch them
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
                    s["member_name"] = member_name
                    s["member_email"] = member_email
                    s["image_url"] = f"/proxy-image?workeye_url={base_url}&token={token}&screenshot_id={s['id']}"

                all_screenshots.extend(screenshots)

        except Exception as e:
            print(f"Failed to get screenshots for member {member_id}: {e}")
            continue

    # Sort by timestamp descending (newest first)
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
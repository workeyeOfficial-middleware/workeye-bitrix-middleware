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
    # Log the FULL raw stats object so we can see every field WorkEye actually returns
    print(f"[stats] RAW top-level keys: {list(data.keys())}")
    print(f"[stats] RAW stats keys: {list(stats.keys())}")
    print(f"[stats] RAW stats values: {stats}")

    # dashboard/stats returns only aggregate stats with no members array.
    # Fetch full member list (with devices, position, department, etc.) separately.
    if not members:
        print("[stats] No members in dashboard/stats — fetching from members endpoint")
        members = _fetch_members_list(base_url, headers)

    # Log all keys from first member to help debug field names
    if members:
        print(f"[stats] First member keys: {list(members[0].keys())}")
        print(f"[stats] First member raw: {members[0]}")

    # Fetch department map and merge into members (department is often missing from stats endpoint)
    dept_map = _fetch_department_map(base_url, headers)
    if dept_map:
        for m in members:
            if not m.get("department"):
                dept = dept_map.get(m.get("id")) or dept_map.get(m.get("email"))
                if dept:
                    m["department"] = dept
                    print(f"[stats] Assigned department '{dept}' to {m.get('name')}")

    # Normalize devices field — check known keys directly on member first,
    # then fall back to a dedicated device map lookup
    _device_keys = [
        "device_count",                    # WorkEye's actual field name
        "devices", "devices_count", "num_devices", "total_devices",
        "devicesCount", "deviceCount", "device",
        "connected_devices", "active_devices", "machine_count", "machines",
        "computers", "computer_count", "computersCount", "num_computers",
        "total_computers", "endpoints", "endpoint_count",
    ]
    for m in members:
        if not m.get("devices"):
            for key in _device_keys:
                if m.get(key) is not None:
                    m["devices"] = m[key]
                    break
            if not m.get("devices"):
                for key, val in m.items():
                    if (
                        "device" in key.lower() or "machine" in key.lower() or
                        "computer" in key.lower() or "endpoint" in key.lower()
                    ) and val is not None:
                        print(f"[stats] Found device field via scan: {key}={val}")
                        m["devices"] = val
                        break

    # If any members still lack device data, fetch via dedicated device map
    if any(not m.get("devices") for m in members):
        device_map = _fetch_device_map(base_url, headers, members)
        if device_map:
            for m in members:
                if not m.get("devices"):
                    val = device_map.get(m.get("id")) or device_map.get(m.get("email"))
                    if val is not None:
                        m["devices"] = val

    total   = len(members)
    active  = sum(1 for m in members if (m.get("status") or "").lower() == "active")
    idle    = sum(1 for m in members if (m.get("status") or "").lower() == "idle")
    offline = total - active - idle
    all_prod = [m.get("productivity", 0) for m in members]
    avg_prod = int(sum(all_prod) / len(all_prod)) if all_prod else 0

    # ── Preserve WorkEye's own change/history fields ──────────────────────────
    preserved = {}
    for key, val in stats.items():
        if val is not None:
            kl = key.lower()
            if any(w in kl for w in ("change", "increase", "decrease", "yesterday",
                                      "previous", "prev", "percent", "growth", "history")):
                preserved[key] = val
                print(f"[stats] Preserved WorkEye change field: {key}={val}")

    # ── Fetch yesterday's data to compute accurate change percentages ──────────
    # Strategy:
    #  1. Try /api/dashboard/activity-trends  — WorkEye's own historical source
    #  2. Try /api/dashboard/stats?date=yesterday — direct stats for that day
    #  3. Fall back to "not available" (frontend shows neutral text)
    yesterday_total = None
    yesterday_prod  = None
    try:
        from datetime import timezone, timedelta as _td
        IST = timezone(_td(hours=5, minutes=30))
        yesterday_str = (datetime.now(IST) - _td(days=1)).strftime("%Y-%m-%d")
        today_str     = datetime.now(IST).strftime("%Y-%m-%d")

        # ── Strategy 1: activity-trends endpoint ──────────────────────────────
        rt = requests.get(f"{base_url}/api/dashboard/activity-trends",
                          headers=headers, timeout=10)
        if rt.status_code == 200:
            td = rt.json()
            print(f"[stats] activity-trends keys: {list(td.keys()) if isinstance(td, dict) else type(td)}")

            # WorkEye typically returns a list of daily records or a dict with daily arrays.
            # We look for yesterday's entry in whatever shape the data comes in.
            def _extract_yesterday(obj, ydate):
                """Recursively find a record matching yesterday's date and return
                (total_members, avg_productivity) or (None, None)."""
                if isinstance(obj, list):
                    for item in obj:
                        if isinstance(item, dict):
                            d = (item.get("date") or item.get("day") or
                                 item.get("created_at","")[:10] or "")
                            if d == ydate:
                                tot  = (item.get("total_members") or item.get("total") or
                                        item.get("employee_count") or item.get("headcount"))
                                prod = (item.get("average_productivity") or
                                        item.get("avg_productivity") or
                                        item.get("productivity"))
                                return tot, prod
                if isinstance(obj, dict):
                    for v in obj.values():
                        if isinstance(v, (list, dict)):
                            tot, prod = _extract_yesterday(v, ydate)
                            if tot is not None or prod is not None:
                                return tot, prod
                return None, None

            yesterday_total, yesterday_prod = _extract_yesterday(td, yesterday_str)
            print(f"[stats] Trends: yesterday total={yesterday_total} prod={yesterday_prod}")

        # ── Strategy 2: WorkEye raw stats object already has change fields ─────
        # WorkEye computes employee_increase and productivity_increase itself.
        # Check every possible field name they might use.
        _emp_change_keys = [
            "employee_increase", "employeeIncrease",
            "employee_change", "employeeChange",
            "member_change", "memberChange",
            "total_members_change", "headcount_change",
            "employees_increase", "employee_growth",
            "new_employees", "employee_percent_change",
        ]
        _prod_change_keys = [
            "productivity_increase", "productivityIncrease",
            "productivity_change", "productivityChange",
            "avg_productivity_change", "avgProductivityChange",
            "productivity_growth", "productivity_percent_change",
        ]
        for k in _emp_change_keys:
            if stats.get(k) is not None:
                preserved["employee_change"] = float(stats[k])
                print(f"[stats] Found employee change in raw stats: {k}={stats[k]}")
                break
        for k in _prod_change_keys:
            if stats.get(k) is not None:
                preserved["productivity_change"] = float(stats[k])
                print(f"[stats] Found productivity change in raw stats: {k}={stats[k]}")
                break

        # ── Strategy 3 REMOVED ───────────────────────────────────────────────
        # The WorkEye stats?date=yesterday endpoint ignores the date param and
        # returns today's live data, which makes yesterday_total wrong and causes
        # a false "decrease" when employee count is actually stable/growing.
        # We only trust activity-trends (Strategy 1) for historical data.
        print(f"[stats] Skipping stats?date fallback — unreliable (returns today data)")

    except Exception as ye:
        print(f"[stats] Yesterday fetch failed (non-critical): {ye}")

    # ── Compute change percentages from yesterday data (only if not already set) ──
    # preserved may already have employee_change/productivity_change from the raw
    # stats object scan above — don't overwrite those with computed values.
    if "employee_change" not in preserved:
        if yesterday_total is not None and yesterday_total > 0:
            # We have reliable yesterday data from activity-trends — use it
            computed = round(((total - yesterday_total) / yesterday_total) * 100, 1)
            preserved["employee_change"] = computed
            print(f"[stats] Computed employee_change from trends: {yesterday_total}->{total} = {computed}%")
        else:
            # Check if WorkEye already sent its own increase value in the stats response
            # (captured by the initial keyword-preservation loop above, e.g. "employee_increase")
            _workeye_increase = None
            for _k in _emp_change_keys:
                if _k in preserved:
                    try:
                        _workeye_increase = float(preserved[_k])
                    except (TypeError, ValueError):
                        pass
                    break
            if _workeye_increase is not None:
                preserved["employee_change"] = _workeye_increase
                print(f"[stats] Using WorkEye's own increase value from preserved: {_workeye_increase}%")
            elif total > 0:
                # No reliable yesterday baseline and no WorkEye-provided value — default to 100%
                preserved["employee_change"] = 100.0
                print(f"[stats] No yesterday baseline — defaulting employee_change to 100.0%")
    if "productivity_change" not in preserved and yesterday_prod is not None:
        if yesterday_prod > 0:
            preserved["productivity_change"] = round(
                ((avg_prod - yesterday_prod) / yesterday_prod) * 100, 1)
        elif yesterday_prod == 0 and avg_prod > 0:
            preserved["productivity_change"] = 100.0

    print(f"[stats] Final changes: employee={preserved.get('employee_change')} "
          f"prod={preserved.get('productivity_change')}")

    stats.update({
        "total_members": total, "active_now": active,
        "idle_now": idle, "offline": offline, "average_productivity": avg_prod,
    })
    stats.update(preserved)

    print(f"[stats] Members:{total} Active:{active} Idle:{idle} Offline:{offline} Avg:{avg_prod}%")
    return {"stats": stats, "members": members}



def _fetch_members_list(base_url: str, headers: dict) -> list:
    """
    Fetch the full member list from the first endpoint that returns data.
    Returns a list of member dicts (with all raw fields including devices).
    """
    candidate_urls = [
        f"{base_url}/admin/members",       # WorkEye primary endpoint — returns device_count
        f"{base_url}/api/members",
        f"{base_url}/api/team",
        f"{base_url}/api/users",
        f"{base_url}/api/employees",
        f"{base_url}/api/admin/members",
        f"{base_url}/api/dashboard/members",
    ]
    for url in candidate_urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                continue
            raw = r.json()
            items = (
                raw if isinstance(raw, list) else
                raw.get("members") or raw.get("users") or
                raw.get("employees") or raw.get("data") or raw.get("team") or []
            )
            if items:
                print(f"[members] Got {len(items)} members from {url}")
                print(f"[members] First member keys: {list(items[0].keys()) if items else []}")
                return items
        except Exception as e:
            print(f"[members] {url} failed: {e}")
    print("[members] All endpoints failed — returning empty list")
    return []


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
            # Support {"members":[...]}, {"users":[...]}, {"data":[...]}, {"team":[...]}, or a plain list
            items = (
                raw if isinstance(raw, list) else
                raw.get("members") or raw.get("users") or
                raw.get("employees") or raw.get("team") or raw.get("data") or []
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


def _fetch_device_map(base_url: str, headers: dict, members: list) -> dict:
    """
    Try to find device count for each member.
    Returns a dict keyed by member id (int) and email (str) -> device count/value.
    Strategy:
      1. Try bulk device endpoints first.
      2. Fall back to per-member live endpoint which may include device info.
    """
    device_map = {}
    _dkeys = [
        "device_count",                    # WorkEye's actual field name
        "devices", "devices_count", "num_devices", "total_devices",
        "devicesCount", "deviceCount", "device",
        "connected_devices", "active_devices", "machine_count", "machines",
        "computers", "computer_count", "computersCount", "num_computers",
        "total_computers", "endpoints", "endpoint_count",
    ]

    # 1. Try bulk device endpoints
    bulk_urls = [
        f"{base_url}/admin/members",       # WorkEye primary — has device_count per member
        f"{base_url}/api/devices",
        f"{base_url}/api/computers",
        f"{base_url}/api/machines",
        f"{base_url}/api/endpoints",
        f"{base_url}/api/admin/devices",
        f"{base_url}/api/members/devices",
    ]
    for url in bulk_urls:
        try:
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code != 200:
                continue
            raw = r.json()
            # /admin/members returns {"members": [...]} each with device_count
            items = (
                raw if isinstance(raw, list) else
                raw.get("members") or raw.get("devices") or raw.get("computers") or
                raw.get("machines") or raw.get("data") or []
            )
            if not items:
                continue
            print(f"[device_map] Got {len(items)} records from {url}")
            # If items have device_count directly (e.g. /admin/members), use it
            if any(item.get("device_count") is not None for item in items if isinstance(item, dict)):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    val = item.get("device_count")
                    if val is None:
                        continue
                    if item.get("id"):
                        device_map[item["id"]] = val
                    if item.get("email"):
                        device_map[item["email"]] = val
                if device_map:
                    print(f"[device_map] Built map with {len(device_map)} entries (device_count) from {url}")
                    return device_map
            # Otherwise aggregate count per member_id (device-list endpoints)
            counts = {}
            for item in items:
                mid = item.get("member_id") or item.get("user_id") or item.get("employee_id")
                if mid:
                    counts[mid] = counts.get(mid, 0) + 1
            if counts:
                device_map.update(counts)
                print(f"[device_map] Built map with {len(device_map)} entries from {url}")
                return device_map
        except Exception as e:
            print(f"[device_map] {url} failed: {e}")

    # 2. Try per-member live endpoint (only for members missing device data)
    missing = [m for m in members if m.get("id") and not device_map.get(m.get("id"))]
    if missing:
        print(f"[device_map] Trying per-member live for {len(missing)} members")
        for m in missing[:20]:  # cap at 20 to avoid hammering the API
            mid = m.get("id")
            try:
                r = requests.get(f"{base_url}/api/dashboard/member/{mid}/live",
                                 headers=headers, timeout=8)
                if r.status_code != 200:
                    continue
                data = r.json()
                # Search the entire response for device-like fields
                def _find_devices(obj, depth=0):
                    if depth > 3:
                        return None
                    if isinstance(obj, dict):
                        for k in _dkeys:
                            if obj.get(k) is not None:
                                return obj[k]
                        for k, v in obj.items():
                            if ("device" in k.lower() or "machine" in k.lower()
                                    or "computer" in k.lower()):
                                return v
                        for v in obj.values():
                            result = _find_devices(v, depth + 1)
                            if result is not None:
                                return result
                    elif isinstance(obj, list):
                        for item in obj:
                            result = _find_devices(item, depth + 1)
                            if result is not None:
                                return result
                    return None

                val = _find_devices(data)
                if val is not None:
                    device_map[mid] = val
                    print(f"[device_map] Found devices={val} for member {mid} via live endpoint")
            except Exception as e:
                print(f"[device_map] live for {mid} failed: {e}")

    return device_map


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
    from datetime import timezone, timedelta
    headers = {"Authorization": f"Bearer {token}"}

    # Determine the target date in IST (default = today IST)
    IST = timezone(timedelta(hours=5, minutes=30))
    if date:
        target_date = date  # YYYY-MM-DD string passed from frontend
    else:
        target_date = datetime.now(IST).strftime("%Y-%m-%d")

    try:
        url = f"{base_url}/api/attendance/members"
        params = {"date": target_date}
        r = requests.get(url, headers=headers, params=params, timeout=20)

        if r.status_code == 200:
            data = r.json()
            print(f"[attendance] Raw keys: {list(data.keys())} for date={target_date}")
            members = data.get("attendance") or data.get("members") or data.get("data") or []

            if members:
                result = []
                for m in members:
                    today_minutes = float(m.get("today_minutes") or m.get("today_hours_raw") or 0)
                    today_hours   = float(m.get("today_hours") or m.get("hours_worked") or 0)
                    is_punched_in = m.get("is_punched_in", False)

                    # WorkEye bug: punch_in_time falls back to last_punch_in_at (any day)
                    # Only use punch times if the employee has actual activity TODAY
                    # i.e. today_minutes > 0 OR is_punched_in is True
                    has_today_activity = is_punched_in or today_hours > 0 or today_minutes > 0

                    punch_in  = (m.get("punch_in_time") or m.get("punch_in") or
                                 m.get("check_in") or m.get("check_in_time") or None)
                    punch_out = (m.get("punch_out_time") or m.get("punch_out") or
                                 m.get("check_out") or m.get("check_out_time") or None)

                    # If no activity today, blank out the stale historical punch times
                    if not has_today_activity:
                        punch_in  = None
                        punch_out = None

                    # Extra safety: if punch_in date doesn't match target_date, blank it
                    if punch_in and len(str(punch_in)) >= 10:
                        punch_date = str(punch_in)[:10]
                        if punch_date != target_date:
                            punch_in  = None
                            punch_out = None

                    print(f"[attendance] {m.get('name')} | date={target_date} | "
                          f"today_h={today_hours} | punched={is_punched_in} | "
                          f"in={punch_in} | out={punch_out}")

                    result.append({
                        "id":             m.get("id"),
                        "name":           m.get("name"),
                        "email":          m.get("email"),
                        "position":       m.get("position"),
                        "department":     m.get("department"),
                        "status":         m.get("status"),
                        "punch_in_time":  punch_in,
                        "punch_out_time": punch_out,
                        "today_hours":    round(today_hours, 1),
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
    from datetime import timezone, timedelta as _td
    import screenshot_cache as _sc

    headers = {"Authorization": f"Bearer {token}"}

    # Default date = today in IST (same timezone WorkEye uses)
    IST = timezone(_td(hours=5, minutes=30))
    if not date:
        date = datetime.now(IST).strftime("%Y-%m-%d")

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
            # Use a high limit to avoid missing screenshots; also pass date so
            # WorkEye filters server-side (reduces payload and avoids cross-day bleed)
            params = {"limit": 500, "offset": 0, "date": date,
                      "start_date": date, "end_date": date}
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
                print(f"[screenshots] Member {member_id} ({member_name}): {len(screenshots)} screenshots")
                all_screenshots.extend(screenshots)
        except Exception as e:
            print(f"[screenshots] Member {member_id} failed: {e}")
            continue

    # Always filter to the requested date so cross-day bleed from the API is removed
    all_screenshots = [s for s in all_screenshots if (s.get("timestamp") or "").startswith(date)]
    all_screenshots.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    # Save fresh results to cache (keyed by today's date) so the cache stays current
    if all_screenshots:
        try:
            _sc.save_screenshots(all_screenshots)
            print(f"[screenshots] Saved {len(all_screenshots)} screenshots to cache for {date}")
        except Exception as ce:
            print(f"[screenshots] Cache save failed (non-critical): {ce}")

    print(f"[screenshots] Total for {date}: {len(all_screenshots)}")
    return all_screenshots


# =========================
# IMAGE FETCH
# =========================
# =========================
# ADMIN PROFILE
# =========================
def get_admin_profile(base_url: str, token: str) -> dict:
    import base64, json as _json
    headers = {"Authorization": f"Bearer {token}"}

    # Decode admin_id and company_id from JWT
    try:
        payload = token.split(".")[1]
        padded = payload + "=" * (4 - len(payload) % 4)
        jwt_data = _json.loads(base64.urlsafe_b64decode(padded))
        admin_id = jwt_data.get("admin_id") or jwt_data.get("user_id")
        company_id = jwt_data.get("company_id") or jwt_data.get("tenant_id")
    except Exception:
        admin_id = None
        company_id = None

    # Try dedicated profile/company endpoints first
    profile_candidates = [
        f"{base_url}/api/admin/profile",
        f"{base_url}/api/admin/me",
        f"{base_url}/api/me",
        f"{base_url}/api/profile",
        f"{base_url}/auth/admin/profile",
        f"{base_url}/api/account",
        f"{base_url}/api/company/{company_id}" if company_id else None,
        f"{base_url}/api/admin/{admin_id}" if admin_id else None,
        f"{base_url}/api/admin/settings",
        f"{base_url}/api/settings/profile",
        f"{base_url}/api/configuration",
    ]
    for url in profile_candidates:
        if not url:
            continue
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                profile = data.get("admin") or data.get("user") or data.get("profile") or data.get("data") or data
                if isinstance(profile, dict) and (profile.get("name") or profile.get("company_name") or profile.get("company")):
                    print(f"[profile] Found at {url}: {list(profile.keys())}")
                    return profile
        except Exception:
            continue

    # Fallback: find admin in /admin/members by admin_id
    if admin_id:
        try:
            for path in [f"{base_url}/admin/members", f"{base_url}/api/admin/members"]:
                r = requests.get(path, headers=headers, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    members = data if isinstance(data, list) else (data.get("members") or data.get("data") or data.get("users") or [])
                    for m in members:
                        if m.get("id") == admin_id or m.get("user_id") == admin_id:
                            print(f"[profile] Found admin in members list: {list(m.keys())}")
                            return m
        except Exception:
            pass

    print("[profile] No profile data found")
    return {}


# =========================
# BILLING / SUBSCRIPTION
# =========================
PRODUCT_ID = "69589e3fe70228ef3c25f26c"
LMS_API_KEY = "my-secret-key-123"

def get_billing(base_url: str, token: str) -> dict:
    """
    Fetch the active license/plan for this company from the WorkEye LMS.
    Endpoint discovered from BillingPage.tsx:
      GET /api/license-proxy/api/external/actve-license/{email}?productId=...
    Email is decoded from the JWT token.
    """
    import base64 as _b64, json as _json

    # Decode email from JWT
    email = None
    try:
        payload = token.split(".")[1]
        padded = payload + "=" * (4 - len(payload) % 4)
        jwt_data = _json.loads(_b64.urlsafe_b64decode(padded))
        email = (
            jwt_data.get("email") or
            jwt_data.get("sub") or
            jwt_data.get("adminEmail") or
            jwt_data.get("admin_email")
        )
        print(f"[billing] JWT keys: {list(jwt_data.keys())} email={email}")
    except Exception as e:
        print(f"[billing] JWT decode failed: {e}")

    if not email:
        # Fallback: try admin profile to get email
        try:
            profile = get_admin_profile(base_url, token)
            email = profile.get("email")
            print(f"[billing] Got email from profile: {email}")
        except Exception as e:
            print(f"[billing] Profile fallback failed: {e}")

    if not email:
        return {"plan_name": "Unknown", "status": "unknown", "expires_at": None}

    lms_url = (
        f"{base_url}/api/license-proxy/api/external/actve-license"
        f"/{requests.utils.quote(email, safe='')}?productId={PRODUCT_ID}"
    )
    headers = {"x-api-key": LMS_API_KEY}

    try:
        r = requests.get(lms_url, headers=headers, timeout=10)
        print(f"[billing] LMS status: {r.status_code} url: {lms_url}")
        if r.status_code != 200:
            return {"plan_name": "Unknown", "status": "unknown", "expires_at": None}

        data = r.json()
        print(f"[billing] Raw top-level keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        lic = data.get("activeLicense") or data.get("license") or data.get("data") or data
        print(f"[billing] License keys: {list(lic.keys()) if isinstance(lic, dict) else type(lic)}")
        print(f"[billing] License raw: {str(lic)[:400]}")

        expires_at = lic.get("endDate") or lic.get("expireAt") or lic.get("expiresAt") or None
        status = lic.get("status") or "active"
        billing_cycle = lic.get("billingCycle") or None

        # Exactly what BillingPage.tsx does:
        # Step 1 — extract licenseTypeId (may be nested object or plain string)
        lt_field = lic.get("licenseTypeId")
        if isinstance(lt_field, dict):
            license_type_id = lt_field.get("_id", "")
        elif lt_field:
            license_type_id = str(lt_field)
        else:
            # fallback: try licenseType field
            lt2 = lic.get("licenseType")
            if isinstance(lt2, dict):
                license_type_id = lt2.get("_id", "")
            else:
                license_type_id = str(lt2) if lt2 else ""

        print(f"[billing] licenseTypeId resolved: {license_type_id}")

        # Step 2 — fetch plans list and match by licenseTypeId (exactly like BillingPage.tsx)
        plan_name = None
        if license_type_id:
            try:
                plans_url = f"{base_url}/api/license-proxy/api/license/public/licenses-by-product/{PRODUCT_ID}"
                pr = requests.get(plans_url, timeout=10)
                print(f"[billing] Plans list status: {pr.status_code}")
                if pr.status_code == 200:
                    pdata = pr.json()
                    raw_plans = (
                        pdata.get("licenses") or
                        (pdata.get("data") or {}).get("licenses") or
                        pdata.get("data") or
                        (pdata if isinstance(pdata, list) else [])
                    )
                    print(f"[billing] Plans count: {len(raw_plans)}")
                    for p in raw_plans:
                        lt = p.get("licenseType") or p
                        lt_id = lt.get("_id") if isinstance(lt, dict) else None
                        lt_name = lt.get("name") if isinstance(lt, dict) else None
                        print(f"[billing] Plan: id={lt_id} name={lt_name}")
                        if lt_id and lt_id == license_type_id:
                            plan_name = lt_name
                            break
            except Exception as pe:
                print(f"[billing] Plans lookup failed: {pe}")

        # Step 3 — fallbacks (same order as BillingPage.tsx line 567)
        if not plan_name:
            lt = lic.get("licenseType")
            plan_name = (
                (lt.get("name") if isinstance(lt, dict) else None) or
                lic.get("planName") or
                lic.get("name") or
                "Unknown"
            )

        print(f"[billing] FINAL plan={plan_name} status={status} expires={expires_at}")
        return {
            "plan_name": str(plan_name).strip(),
            "status": str(status).strip().lower(),
            "expires_at": expires_at,
            "billing_cycle": billing_cycle,
        }
    except Exception as e:
        print(f"[billing] LMS fetch failed: {e}")
        return {"plan_name": "Unknown", "status": "unknown", "expires_at": None}


def get_screenshot_image(base_url: str, token: str, screenshot_id: int) -> bytes:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/api/screenshots/image/{screenshot_id}"
    r = requests.get(url, headers=headers, timeout=15)
    print(f"[image] Status: {r.status_code} id:{screenshot_id}")
    if r.status_code != 200:
        raise Exception(f"Image failed: {r.status_code} - {r.text[:100]}")
    return r.content
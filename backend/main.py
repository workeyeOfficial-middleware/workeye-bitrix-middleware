from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import workeye_service as ws
import bitrix_service as bs
import bitrix_routes
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup Bitrix24 routes
bitrix_routes.setup_bitrix_routes(app)

# ── Serve frontend ────────────────────────────────────────
@app.get("/")
@app.post("/")
async def serve_index():
    index_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content=content)
    return HTMLResponse(content="<h1>WorkEye Monitor</h1>")

@app.get("/index.html")
@app.post("/index.html")
async def serve_index_html():
    return await serve_index()

def _serve_html(filename: str) -> HTMLResponse:
    """Helper to serve any HTML file from the project root or frontend folder."""
    base = os.path.dirname(__file__)
    # Check project root first, then frontend folder
    for path in [
        os.path.join(base, "..", filename),
        os.path.join(base, "..", "frontend", filename),
    ]:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
    return HTMLResponse(content=f"<h1>Page not found: {filename}</h1>", status_code=404)

@app.get("/privacy")
@app.get("/privacy.html")
async def serve_privacy():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="https://workeye.org/privacy", status_code=301)

@app.get("/eula")
@app.get("/eula.html")
async def serve_eula():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="https://workeye.org/eula", status_code=301)

@app.get("/contact")
@app.get("/contact.html")
async def serve_contact():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="https://workeye.org/contact", status_code=301)

# ── Auth ─────────────────────────────────────────────────
class Creds(BaseModel):
    email: str
    password: str
    workeye_url: Optional[str] = "https://backend-35m2.onrender.com"

@app.post("/login")
async def login(creds: Creds):
    try:
        result = ws.get_token(creds.workeye_url, creds.email, creds.password)
        return {"success": True, "token": result["token"], "profile": result["profile"], "workeye_url": creds.workeye_url}
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

@app.get("/get-admin-profile")
async def get_admin_profile(workeye_url: str, token: str):
    try:
        data = ws.get_admin_profile(workeye_url, token)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Debug Login Response ─────────────────────────────────
@app.post("/debug-login")
async def debug_login(creds: Creds):
    import requests as req
    url = f"{creds.workeye_url}/auth/admin/login"
    r = req.post(url, json={"email": creds.email, "password": creds.password},
                 headers={"Content-Type": "application/json"}, timeout=30)
    return {"status": r.status_code, "body": r.json()}

# ── Stats ────────────────────────────────────────────────
@app.get("/get-stats")
async def get_stats(workeye_url: str, token: str):
    try:
        data = ws.get_stats(workeye_url, token)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Debug: dump raw /api/dashboard/stats keys + values ───
@app.get("/debug-raw-stats")
async def debug_raw_stats(workeye_url: str, token: str):
    """Returns the complete raw stats object from WorkEye so we can see
    every field name and value — use this to find change/history fields."""
    import requests as req
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = req.get(f"{workeye_url}/api/dashboard/stats", headers=headers, timeout=15)
        raw = r.json() if r.status_code == 200 else {}
        stats = raw.get("stats", {})
        # Also probe /api/dashboard/stats?date=yesterday
        from datetime import datetime, timedelta, timezone
        IST = timezone(timedelta(hours=5, minutes=30))
        yesterday = (datetime.now(IST) - timedelta(days=1)).strftime("%Y-%m-%d")
        r2 = req.get(f"{workeye_url}/api/dashboard/stats", headers=headers,
                     params={"date": yesterday}, timeout=15)
        stats_yesterday = r2.json().get("stats", {}) if r2.status_code == 200 else {}
        return {
            "today_stats_keys": list(stats.keys()),
            "today_stats": stats,
            "yesterday_stats_keys": list(stats_yesterday.keys()),
            "yesterday_stats": stats_yesterday,
            "yesterday_date": yesterday,
        }
    except Exception as e:
        return {"error": str(e)}

# ── Debug: dump EVERYTHING WorkEye returns ───────────────
@app.get("/debug-all")
async def debug_all(workeye_url: str, token: str):
    """Dumps the complete raw response from every key endpoint.
    Visit this URL after deploying to see exact field names."""
    import requests as req
    headers = {"Authorization": f"Bearer {token}"}
    out = {}

    # 1. Full /api/dashboard/stats raw response
    try:
        r = req.get(f"{workeye_url}/api/dashboard/stats", headers=headers, timeout=15)
        raw = r.json() if r.status_code == 200 else {}
        out["dashboard_stats"] = {
            "top_level_keys": list(raw.keys()) if isinstance(raw, dict) else str(type(raw)),
            "stats_object": raw.get("stats", {}),
            "stats_keys": list(raw.get("stats", {}).keys()),
        }
    except Exception as e:
        out["dashboard_stats"] = {"error": str(e)}

    # 2. Full activity-trends raw response
    try:
        r = req.get(f"{workeye_url}/api/dashboard/activity-trends", headers=headers, timeout=15)
        raw = r.json() if r.status_code == 200 else {}
        trends = raw.get("trends") if isinstance(raw, dict) else raw
        out["activity_trends"] = {
            "top_level_keys": list(raw.keys()) if isinstance(raw, dict) else str(type(raw)),
            "trends_type": str(type(trends)),
            "trends_sample": trends[:3] if isinstance(trends, list) else (str(trends)[:500] if trends else None),
            "trends_keys_in_first_item": list(trends[0].keys()) if isinstance(trends, list) and trends and isinstance(trends[0], dict) else None,
        }
    except Exception as e:
        out["activity_trends"] = {"error": str(e)}

    return out

# ── Debug: dump activity-trends raw response ─────────────
@app.get("/debug-trends")
async def debug_trends(workeye_url: str, token: str):
    """Returns raw /api/dashboard/activity-trends so we can see
    what historical fields WorkEye actually provides."""
    import requests as req
    headers = {"Authorization": f"Bearer {token}"}
    results = {}
    # Try several date-parameterised variants too
    from datetime import datetime, timedelta, timezone
    IST = timezone(timedelta(hours=5, minutes=30))
    yesterday = (datetime.now(IST) - timedelta(days=1)).strftime("%Y-%m-%d")
    today     = datetime.now(IST).strftime("%Y-%m-%d")
    candidates = [
        f"{workeye_url}/api/dashboard/activity-trends",
        f"{workeye_url}/api/dashboard/productivity-trends",
        f"{workeye_url}/api/dashboard/stats/history",
        f"{workeye_url}/api/dashboard/daily-stats",
        f"{workeye_url}/api/reports/daily",
        f"{workeye_url}/api/reports/productivity",
    ]
    for url in candidates:
        try:
            r = req.get(url, headers=headers, timeout=8)
            results[url] = {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:200]}
        except Exception as e:
            results[url] = {"error": str(e)}
    return results

# ── Debug: show raw fields WorkEye returns for members ───
@app.get("/debug-member-fields")
async def debug_member_fields(workeye_url: str, token: str):
    """Returns the raw keys and values of the first member from WorkEye's stats API,
    plus the raw response from every candidate members/users endpoint.
    Use this to find the real department field name."""
    import requests as req
    headers = {"Authorization": f"Bearer {token}"}
    result = {}

    # 1. Raw first member from dashboard/stats
    try:
        r = req.get(f"{workeye_url}/api/dashboard/stats", headers=headers, timeout=15)
        if r.status_code == 200:
            members = r.json().get("members", [])
            result["stats_first_member"] = members[0] if members else {}
            result["stats_member_keys"] = list(members[0].keys()) if members else []
    except Exception as e:
        result["stats_error"] = str(e)

    # 2. Try every candidate endpoint and show raw response
    candidates = [
        "/api/members", "/api/users", "/api/employees",
        "/api/team", "/api/admin/members", "/api/admin/users",
        "/api/dashboard/members", "/api/member/list",
    ]
    endpoint_results = {}
    for path in candidates:
        try:
            r = req.get(f"{workeye_url}{path}", headers=headers, timeout=8)
            endpoint_results[path] = {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:200]}
        except Exception as e:
            endpoint_results[path] = {"error": str(e)}
    result["candidate_endpoints"] = endpoint_results

    return result

# ── Trends ───────────────────────────────────────────────
@app.get("/get-trends")
async def get_trends(workeye_url: str, token: str):
    try:
        data = ws.get_activity_trends(workeye_url, token)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Attendance ───────────────────────────────────────────
@app.get("/get-attendance")
async def get_attendance(workeye_url: str, token: str, date: str = None):
    try:
        data = ws.get_attendance(workeye_url, token, date)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Screenshots ──────────────────────────────────────────
@app.get("/get-screenshots")
async def get_screenshots(workeye_url: str, token: str, date: str = None):
    try:
        import screenshot_cache
        # Always fetch fresh from WorkEye (saves to cache automatically)
        try:
            data = ws.get_screenshots(workeye_url, token, date)
            if data:
                return {"success": True, "data": data}
        except:
            pass
        # Fallback to local cache
        data = screenshot_cache.get_screenshots_by_date(date)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Proxy image ──────────────────────────────────────────
@app.get("/proxy-image")
async def proxy_image(workeye_url: str, token: str, screenshot_id: int, email: str = None, password: str = None):
    try:
        try:
            image_bytes = ws.get_screenshot_image(workeye_url, token, screenshot_id)
        except Exception as e:
            if ("401" in str(e) or "404" in str(e) or "403" in str(e)) and email and password:
                new_token = ws.get_token(workeye_url, email, password)["token"]
                image_bytes = ws.get_screenshot_image(workeye_url, new_token, screenshot_id)
            else:
                raise e
        return Response(content=image_bytes, media_type="image/webp")
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Configuration ─────────────────────────────────────────
@app.get("/get-configuration")
async def get_configuration(workeye_url: str, token: str):
    try:
        data = ws.get_configuration(workeye_url, token)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Attendance Member Detail ──────────────────────────────
@app.get("/get-attendance-member")
async def get_attendance_member(workeye_url: str, token: str, member_id: int, start_date: str = None, end_date: str = None):
    try:
        data = ws.get_attendance_member(workeye_url, token, member_id, start_date, end_date)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Activity Logs ─────────────────────────────────────────
@app.get("/get-activity-logs")
async def get_activity_logs(workeye_url: str, token: str, member_id: int, date: str = None):
    try:
        data = ws.get_activity_logs(workeye_url, token, member_id, date)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Member Screenshots (cached) ───────────────────────────
@app.get("/get-member-screenshots")
async def get_member_screenshots(workeye_url: str, token: str, member_id: int, date: str = None):
    try:
        import screenshot_cache

        # Try cache first
        cached = screenshot_cache.get_screenshots_by_member_date(member_id, date)
        if cached:
            return {"success": True, "data": cached, "source": "cache"}

        # Cache empty — fetch fresh directly from WorkEye API for this member
        headers = {"Authorization": f"Bearer {token}"}
        import requests as req
        params = {"limit": 200, "offset": 0}
        if date:
            params["date"] = date
            params["start_date"] = date
            params["end_date"] = date

        url = f"{workeye_url}/api/screenshots/{member_id}"
        r = req.get(url, headers=headers, params=params, timeout=15)

        screenshots = []
        if r.status_code == 200:
            data = r.json()
            screenshots = data.get("screenshots") or data.get("data") or []
            # Enrich with member_id
            for s in screenshots:
                s["member_id"] = member_id
                if s.get("screenshot_url"):
                    s["image_url"] = s["screenshot_url"]
            # Save to cache for next time
            if screenshots:
                screenshot_cache.save_screenshots(screenshots)

        # Filter by date client-side as safety net
        if date and screenshots:
            screenshots = [s for s in screenshots if (s.get("timestamp") or "").startswith(date)]

        return {"success": True, "data": screenshots, "source": "live"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/debug-billing")
async def debug_billing(workeye_url: str, token: str):
    """
    Probes every plausible billing/subscription endpoint on the WorkEye backend
    and returns the raw status + body for each so we can find the real one.
    """
    import requests as req
    headers = {"Authorization": f"Bearer {token}"}
    candidates = [
        "/api/billing",
        "/api/billing/current",
        "/api/billing/subscription",
        "/api/subscription",
        "/api/plan",
        "/api/plans",
        "/api/company/subscription",
        "/api/company/plan",
        "/api/admin/billing",
        "/api/admin/subscription",
        "/api/admin/plan",
        "/api/account/subscription",
        "/api/account/billing",
        "/api/account",
        "/billing",
        "/subscription",
        "/api/company",
        "/api/admin/company",
        "/api/settings",
        "/api/admin/settings",
        "/api/configuration",
    ]
    results = {}
    for path in candidates:
        url = f"{workeye_url}{path}"
        try:
            r = req.get(url, headers=headers, timeout=8)
            try:
                body = r.json()
            except Exception:
                body = r.text[:300]
            results[path] = {"status": r.status_code, "body": body}
        except Exception as e:
            results[path] = {"error": str(e)}
    return results


@app.get("/get-billing")
async def get_billing(workeye_url: str, token: str):
    try:
        data = ws.get_billing(workeye_url, token)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Sync ─────────────────────────────────────────────────
@app.post("/sync-dashboard")
async def sync_dashboard(workeye_url: str, token: str):
    try:
        data = ws.get_stats(workeye_url, token)
        result = bs.sync_dashboard(data)
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sync-employees")
async def sync_employees(workeye_url: str, token: str):
    try:
        data = ws.get_stats(workeye_url, token)
        members = data.get("members", [])
        result = bs.sync_employees(members)
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sync-attendance")
async def sync_attendance(workeye_url: str, token: str):
    try:
        data = ws.get_attendance(workeye_url, token)
        result = bs.sync_attendance(data)
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sync-screenshots")
async def sync_screenshots(workeye_url: str, token: str):
    try:
        data = ws.get_screenshots(workeye_url, token)
        result = bs.sync_screenshots(data)
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
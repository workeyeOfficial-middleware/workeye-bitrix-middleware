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

# ── Auth ─────────────────────────────────────────────────
class Creds(BaseModel):
    email: str
    password: str
    workeye_url: Optional[str] = "https://backend-35m2.onrender.com"

@app.post("/login")
async def login(creds: Creds):
    try:
        token = ws.get_token(creds.workeye_url, creds.email, creds.password)
        return {"success": True, "token": token, "workeye_url": creds.workeye_url}
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

@app.get("/get-admin-profile")
async def get_admin_profile(workeye_url: str, token: str):
    try:
        data = ws.get_admin_profile(workeye_url, token)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Stats ────────────────────────────────────────────────
@app.get("/get-stats")
async def get_stats(workeye_url: str, token: str):
    try:
        data = ws.get_stats(workeye_url, token)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
                new_token = ws.get_token(workeye_url, email, password)
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
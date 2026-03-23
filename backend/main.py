from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import workeye_service as ws
import bitrix_service as bs
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ══════════════════════════════════════════════════════════════════════════════
# ████████████████████ BITRIX24 INTEGRATION ENDPOINTS ████████████████████
# ══════════════════════════════════════════════════════════════════════════════

# ── Bitrix Install Handler ────────────────────────────────────────────────────
@app.get("/bitrix/install")
@app.post("/bitrix/install")
async def bitrix_install(
    AUTH_ID: Optional[str] = None,
    AUTH_EXPIRES: Optional[int] = 3600,
    REFRESH_ID: Optional[str] = None,
    member_id: Optional[str] = None,
    DOMAIN: Optional[str] = None,
):
    """
    Bitrix24 OAuth callback when user installs the app
    
    Receives:
    - AUTH_ID: Access token from Bitrix24
    - REFRESH_ID: Refresh token
    - member_id: Bitrix24 portal ID
    - DOMAIN: Bitrix24 domain
    
    Returns: "OK"
    
    What it does:
    1. Receive tokens from Bitrix24
    2. Save to database (TODO: implement DB save)
    3. Return "OK" to confirm
    """
    try:
        if AUTH_ID and REFRESH_ID and member_id and DOMAIN:
            print(f"✓ Bitrix24 app installed for {member_id} on {DOMAIN}")
            
            # TODO: Save to database
            # Example with MongoDB:
            # db.portals.insert_one({
            #     "member_id": member_id,
            #     "domain": DOMAIN,
            #     "access_token": AUTH_ID,
            #     "refresh_token": REFRESH_ID,
            #     "expires_at": datetime.now() + timedelta(seconds=AUTH_EXPIRES)
            # })
            
            return Response(content="OK", status_code=200)
        
        # Bitrix validation ping (when no params sent)
        return Response(content="OK", status_code=200)
    
    except Exception as e:
        print(f"❌ Bitrix install error: {e}")
        # Always return OK to avoid Bitrix retries
        return Response(content="OK", status_code=200)


# ── Bitrix Uninstall Handler ──────────────────────────────────────────────────
@app.post("/bitrix/uninstall")
async def bitrix_uninstall(member_id: Optional[str] = None):
    """
    Called when user uninstalls the app from Bitrix24
    
    Receives:
    - member_id: Portal ID to delete
    
    Returns: "OK"
    
    What it does:
    1. Receive member_id
    2. Delete all app data for this portal
    3. Return "OK" to confirm
    """
    try:
        if member_id:
            print(f"✓ Bitrix24 app uninstalled for {member_id}")
            
            # TODO: Delete from database
            # Example:
            # db.portals.delete_one({"member_id": member_id})
        
        return Response(content="OK", status_code=200)
    
    except Exception as e:
        print(f"❌ Bitrix uninstall error: {e}")
        # Always return OK
        return Response(content="OK", status_code=200)


# ── Bitrix App Launcher ───────────────────────────────────────────────────────
@app.get("/bitrix/app")
@app.post("/bitrix/app")
async def bitrix_app_launcher(DOMAIN: Optional[str] = None, member_id: Optional[str] = None):
    """
    Called when Bitrix24 loads your app in an iframe
    
    Receives:
    - DOMAIN: Bitrix24 domain
    - member_id: Portal ID
    
    Returns: HTML or redirect
    
    What it does:
    1. Receive Bitrix context
    2. Load your app UI (or redirect to frontend)
    3. App shows inside Bitrix24 iframe
    """
    try:
        if DOMAIN:
            print(f"✓ Bitrix24 app loaded for {DOMAIN}")
            # Redirect to your frontend with domain
            return {
                "redirect": f"/?domain={DOMAIN}&member_id={member_id}"
            }
        
        return Response(content="OK", status_code=200)
    
    except Exception as e:
        print(f"❌ Bitrix app launcher error: {e}")
        return Response(content="OK", status_code=200)

# ══════════════════════════════════════════════════════════════════════════════
# ████████████████████ YOUR EXISTING ENDPOINTS (KEEP ALL) ████████████████████
# ══════════════════════════════════════════════════════════════════════════════

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

# ── Stats ────────────────────────────────────────────────
@app.get("/get-stats")
async def get_stats(workeye_url: str, token: str):
    try:
        data = ws.get_stats(workeye_url, token)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
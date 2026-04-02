from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import workeye_service as ws
import bitrix_service as bs
import bitrix_routes
import os
import database
database.init_db()

app = FastAPI()

# ✅ CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ ✅ IMPORTANT: Allow Bitrix iframe (FIXES INFINITE LOADING)
@app.middleware("http")
async def allow_iframe(request, call_next):
    response = await call_next(request)

    # ❌ REMOVE invalid header
    response.headers.pop("X-Frame-Options", None)

    # ✅ Allow Bitrix iframe
    response.headers["Content-Security-Policy"] = (
        "frame-ancestors https://*.bitrix24.com https://*.bitrix24.ru"
    )

    return response

# ✅ Optional: request logging (debug)
@app.middleware("http")
async def log_requests(request, call_next):
    print(f"➡️ {request.method} {request.url}")
    response = await call_next(request)
    return response


# ✅ Setup Bitrix routes
bitrix_routes.setup_bitrix_routes(app)


# ── Serve frontend ────────────────────────────────────────
@app.get("/")
@app.post("/")
async def serve_index():
    index_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>WorkEye Monitor</h1>")


@app.get("/index.html")
@app.post("/index.html")
async def serve_index_html():
    return await serve_index()


# ✅ Optional (if you have JS/CSS)
static_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "static")

if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")


# ── Legal redirects ───────────────────────────────────────
@app.get("/privacy")
@app.get("/privacy.html")
async def serve_privacy():
    return RedirectResponse(url="https://workeye.org/privacy", status_code=301)


@app.get("/eula")
@app.get("/eula.html")
async def serve_eula():
    return RedirectResponse(url="https://workeye.org/eula", status_code=301)


@app.get("/contact")
@app.get("/contact.html")
async def serve_contact():
    return RedirectResponse(url="https://workeye.org/contact", status_code=301)


# ── Health check (NEW) ────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}


# ── Auth ─────────────────────────────────────────────────
class Creds(BaseModel):
    email: str
    password: str
    workeye_url: Optional[str] = "https://backend-35m2.onrender.com"


@app.post("/login")
async def login(creds: Creds):
    try:
        result = ws.get_token(creds.workeye_url, creds.email, creds.password)
        return {
            "success": True,
            "token": result["token"],
            "profile": result["profile"],
            "workeye_url": creds.workeye_url,
        }
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

        try:
            data = ws.get_screenshots(workeye_url, token, date)
            if data:
                return {"success": True, "data": data}
        except:
            pass

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


# ── Sync APIs ────────────────────────────────────────────
@app.post("/sync-dashboard")
async def sync_dashboard(workeye_url: str, token: str):
    data = ws.get_stats(workeye_url, token)
    return {"success": True, "result": bs.sync_dashboard(data)}


@app.post("/sync-employees")
async def sync_employees(workeye_url: str, token: str):
    data = ws.get_stats(workeye_url, token)
    return {"success": True, "result": bs.sync_employees(data.get("members", []))}


@app.post("/sync-attendance")
async def sync_attendance(workeye_url: str, token: str):
    data = ws.get_attendance(workeye_url, token)
    return {"success": True, "result": bs.sync_attendance(data)}


@app.post("/sync-screenshots")
async def sync_screenshots(workeye_url: str, token: str):
    data = ws.get_screenshots(workeye_url, token)
    return {"success": True, "result": bs.sync_screenshots(data)}
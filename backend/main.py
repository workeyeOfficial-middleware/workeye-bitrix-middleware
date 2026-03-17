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

# ── Attendance ───────────────────────────────────────────
@app.get("/get-trends")
async def get_trends(workeye_url: str, token: str):
    try:
        data = ws.get_activity_trends(workeye_url, token)
        return {"success": True, "data": data}
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
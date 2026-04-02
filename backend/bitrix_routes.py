"""
bitrix_routes.py — FINAL WORKING VERSION
=========================================
ROOT CAUSE FIX:
- Bitrix24 shows "Loading..." forever when:
  1. App URL returns a redirect instead of HTML directly
  2. BX24.init() is never called
  3. index.html fails to load

SOLUTION:
- /bitrix/install → saves tokens + returns HTML with BX24.init()
- /bitrix/app     → reads index.html from disk and returns it directly
                    NO redirects. NO window.location. Just HTML.
"""

from fastapi import FastAPI, Request
from fastapi.responses import Response, HTMLResponse
from typing import Optional
import os
import database


# Path to index.html (backend runs from /backend dir, frontend is ../frontend)
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
INDEX_PATH   = os.path.join(FRONTEND_DIR, "index.html")


def read_index_html() -> str:
    """Read index.html and return its content. Raises if file not found."""
    if not os.path.exists(INDEX_PATH):
        raise FileNotFoundError(f"index.html not found at {INDEX_PATH}")
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return f.read()


def setup_bitrix_routes(app):

    # ── INSTALL ───────────────────────────────────────────────────────────────
    @app.get("/bitrix/install")
    @app.post("/bitrix/install")
    async def bitrix_install(
        request: Request,
        AUTH_ID: Optional[str] = None,
        AUTH_EXPIRES: Optional[int] = 3600,
        REFRESH_ID: Optional[str] = None,
        member_id: Optional[str] = None,
        DOMAIN: Optional[str] = None,
    ):
        # Parse form data (Bitrix24 sends POST as multipart/form-data)
        try:
            form = await request.form()
            AUTH_ID      = AUTH_ID      or form.get("AUTH_ID")
            REFRESH_ID   = REFRESH_ID   or form.get("REFRESH_ID")
            member_id    = member_id    or form.get("member_id")
            DOMAIN       = DOMAIN       or form.get("DOMAIN")
            AUTH_EXPIRES = int(form.get("AUTH_EXPIRES") or AUTH_EXPIRES or 3600)
        except Exception:
            pass

        # Save tokens to database
        try:
            if AUTH_ID and REFRESH_ID and member_id and DOMAIN:
                print(f"✓ Installed: {member_id} @ {DOMAIN}")
                database.save_portal(
                    member_id=member_id,
                    domain=DOMAIN,
                    access_token=AUTH_ID,
                    refresh_token=REFRESH_ID,
                    expires_in=AUTH_EXPIRES or 3600
                )
        except Exception as e:
            print(f"❌ DB save error: {e}")

        # Return HTML with BX24.init() — Bitrix24 requires this to dismiss loading screen
        return HTMLResponse(content="""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>WorkEye Installed</title>
    <script src="https://api.bitrix24.com/api/v1/"></script>
</head>
<body style="font-family:Arial,sans-serif;text-align:center;padding:60px 20px;background:#f5f5f5;">
    <div style="background:white;border-radius:16px;padding:40px;max-width:400px;margin:0 auto;box-shadow:0 4px 20px rgba(0,0,0,.08)">
        <div style="font-size:48px;margin-bottom:16px">✅</div>
        <h2 style="color:#1e293b;margin-bottom:8px">WorkEye Installed!</h2>
        <p style="color:#64748b;font-size:14px">Open WorkEye from the left menu to get started.</p>
    </div>
    <script>
        BX24.init(function() {
            BX24.resizeWindow(500, 350);
        });
    </script>
</body>
</html>
""", status_code=200)


    # ── UNINSTALL ─────────────────────────────────────────────────────────────
    @app.post("/bitrix/uninstall")
    async def bitrix_uninstall(request: Request, member_id: Optional[str] = None):
        try:
            form = await request.form()
            member_id = member_id or form.get("member_id")
        except Exception:
            pass

        try:
            if member_id:
                print(f"✓ Uninstalled: {member_id}")
                database.delete_portal(member_id)
        except Exception as e:
            print(f"❌ Uninstall error: {e}")

        return Response(content="OK", status_code=200)


    # ── APP LAUNCHER ──────────────────────────────────────────────────────────
    @app.get("/bitrix/app")
    @app.post("/bitrix/app")
    async def bitrix_app_launcher(request: Request):
        """
        Called by Bitrix24 when user opens the app.
        MUST return HTML directly — no redirects, no window.location.
        Bitrix24 shows "Loading..." forever if it gets anything other than
        HTML with BX24.init() called inside it.
        """
        # Read and serve index.html directly
        try:
            html = read_index_html()
            print(f"✓ Serving index.html ({len(html)} bytes) for Bitrix app")
            return HTMLResponse(content=html, status_code=200)

        except FileNotFoundError as e:
            print(f"❌ {e}")
            return HTMLResponse(content="""
<!DOCTYPE html>
<html>
<head>
    <script src="https://api.bitrix24.com/api/v1/"></script>
</head>
<body style="font-family:Arial;padding:40px;text-align:center">
    <h2>⚠️ WorkEye app files not found</h2>
    <p>Please contact support.</p>
    <script>BX24.init(function(){ BX24.resizeWindow(400,200); });</script>
</body>
</html>
""", status_code=200)

        except Exception as e:
            print(f"❌ App launcher error: {e}")
            return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <script src="https://api.bitrix24.com/api/v1/"></script>
</head>
<body style="font-family:Arial;padding:40px;text-align:center">
    <h2>⚠️ Error loading WorkEye</h2>
    <p>{str(e)}</p>
    <script>BX24.init(function(){{ BX24.resizeWindow(400,200); }});</script>
</body>
</html>
""", status_code=200)
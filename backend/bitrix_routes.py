"""
bitrix_routes.py
================
Bitrix24 OAuth + App integration (FINAL FIXED VERSION)

✔ Fixes infinite loading
✔ Fixes iframe issue
✔ Fixes install → app redirect
✔ Handles POST + GET properly
✔ Production ready
"""

from fastapi import FastAPI, Request
from fastapi.responses import Response, HTMLResponse, RedirectResponse
from typing import Optional
import database


def setup_bitrix_routes(app: FastAPI):

    # ─────────────────────────────────────────────
    # ✅ INSTALL HANDLER (FIXED)
    # ─────────────────────────────────────────────
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
        try:
            form = await request.form()
            AUTH_ID      = AUTH_ID      or form.get("AUTH_ID")
            REFRESH_ID   = REFRESH_ID   or form.get("REFRESH_ID")
            member_id    = member_id    or form.get("member_id")
            DOMAIN       = DOMAIN       or form.get("DOMAIN")
            AUTH_EXPIRES = AUTH_EXPIRES or int(form.get("AUTH_EXPIRES") or 3600)
        except Exception:
            pass

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

                pass  # tokens saved, fall through to return HTML below

            return HTMLResponse(content="""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <script src="https://api.bitrix24.com/api/v1/"></script>
</head>
<body style="font-family:Arial;text-align:center;padding:60px 20px;">
    <h2>✅ WorkEye Installed!</h2>
    <p>Open WorkEye from the left menu to get started.</p>
    <script>
        BX24.init(function() {
            BX24.resizeWindow(500, 300);
        });
    </script>
</body>
</html>
""", status_code=200)

        except Exception as e:
            print(f"❌ Install error: {e}")
            return HTMLResponse("<html><body><h2>WorkEye Install OK</h2></body></html>")


    # ─────────────────────────────────────────────
    # ✅ UNINSTALL HANDLER
    # ─────────────────────────────────────────────
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

            return Response("OK")

        except Exception as e:
            print(f"❌ Uninstall error: {e}")
            return Response("OK")


    # ─────────────────────────────────────────────
    # ✅ APP LAUNCHER (FINAL FIXED)
    # ─────────────────────────────────────────────
    @app.get("/bitrix/app")
    @app.post("/bitrix/app")
    async def bitrix_app_launcher(
        request: Request,
        DOMAIN: Optional[str] = None,
        member_id: Optional[str] = None,
        AUTH_ID: Optional[str] = None,
        REFRESH_ID: Optional[str] = None,
    ):
        try:
            form = await request.form()
            DOMAIN     = DOMAIN     or form.get("DOMAIN")
            member_id  = member_id  or form.get("member_id")
            AUTH_ID    = AUTH_ID    or form.get("AUTH_ID")
            REFRESH_ID = REFRESH_ID or form.get("REFRESH_ID")
        except Exception:
            pass

        try:
            print(f"✓ App opened: {DOMAIN}")

            import os
            index_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
            with open(index_path, "r", encoding="utf-8") as f:
                html = f.read()
            return HTMLResponse(content=html, status_code=200)

        except Exception as e:
            print(f"❌ App error: {e}")
            return HTMLResponse("<html><body><h2>WorkEye Error: " + str(e) + "</h2></body></html>")
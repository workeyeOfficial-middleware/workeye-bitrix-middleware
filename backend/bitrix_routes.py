"""
bitrix_routes.py
================
All Bitrix24 OAuth and integration endpoints
Separated from main WorkEye app logic

This keeps Bitrix code isolated and easy to maintain

CHANGES FROM ORIGINAL:
- Filled in TODO: Save to database on install  → uses database.py save_portal()
- Filled in TODO: Delete from database on uninstall → uses database.py delete_portal()
- Install handler now returns HTML instead of plain "OK" (fixes blank iframe)
- App launcher now returns HTML redirect instead of JSON (fixes app not opening)
"""

from fastapi import FastAPI, Request
from fastapi.responses import Response, HTMLResponse
from typing import Optional
import database


def setup_bitrix_routes(app: FastAPI):
    """
    Setup all Bitrix24 endpoints on the FastAPI app
    Call this in main.py to register routes
    """

    # ── Bitrix Install Handler ────────────────────────────────────────────────────
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
        # Bitrix24 sends POST as form-data — parse it
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
                print(f"✓ Bitrix24 app installed for {member_id} on {DOMAIN}")

                # ✅ Save tokens to database
                database.save_portal(
                    member_id     = member_id,
                    domain        = DOMAIN,
                    access_token  = AUTH_ID,
                    refresh_token = REFRESH_ID,
                    expires_in    = AUTH_EXPIRES or 3600
                )

                # ✅ Return HTML so user sees a nice screen, not plain "OK"
                return HTMLResponse(content=f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8" />
    <meta http-equiv="refresh" content="2; url=https://app.workeye.org/bitrix/app?DOMAIN={DOMAIN}&member_id={member_id}" />
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            background: #f0f4ff;
        }}
        .card {{
            text-align: center;
            background: white;
            padding: 40px 50px;
            border-radius: 16px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.08);
        }}
        .icon {{ font-size: 48px; margin-bottom: 16px; }}
        h2 {{ color: #1a56db; font-size: 22px; margin-bottom: 8px; }}
        p  {{ color: #666; font-size: 14px; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">✅</div>
        <h2>WorkEye Installed Successfully!</h2>
        <p>Redirecting to your app...</p>
    </div>
</body>
</html>""", status_code=200)

            # ✅ Bitrix validation ping — redirect to app instead of showing "OK"
            return HTMLResponse(content="""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8" />
    <meta http-equiv="refresh" content="0; url=https://app.workeye.org/bitrix/app" />
</head>
<body>
    <p>Loading WorkEye...</p>
</body>
</html>""", status_code=200)

        except Exception as e:
            print(f"❌ Bitrix install error: {e}")
            return HTMLResponse(content="""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8" /></head>
<body style="font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#fff5f5">
    <div style="text-align:center;background:white;padding:40px 50px;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,0.08)">
        <div style="font-size:48px">⚠️</div>
        <h2 style="color:#e53e3e;margin:12px 0 8px">Installation Error</h2>
        <p style="color:#666;font-size:14px">Something went wrong. Please try reinstalling the app.</p>
    </div>
</body>
</html>""", status_code=200)


    # ── Bitrix Uninstall Handler ──────────────────────────────────────────────────
    @app.post("/bitrix/uninstall")
    async def bitrix_uninstall(request: Request, member_id: Optional[str] = None):
        try:
            form = await request.form()
            member_id = member_id or form.get("member_id")
        except Exception:
            pass

        try:
            if member_id:
                print(f"✓ Bitrix24 app uninstalled for {member_id}")
                # ✅ Delete portal tokens from database
                database.delete_portal(member_id)

            return Response(content="OK", status_code=200)

        except Exception as e:
            print(f"❌ Bitrix uninstall error: {e}")
            return Response(content="OK", status_code=200)


    # ── Bitrix App Launcher ───────────────────────────────────────────────────────
    @app.get("/bitrix/app")
    @app.post("/bitrix/app")
    async def bitrix_app_launcher(
        request: Request,
        DOMAIN: Optional[str] = None,
        member_id: Optional[str] = None,
    ):
        try:
            form = await request.form()
            DOMAIN    = DOMAIN    or form.get("DOMAIN")
            member_id = member_id or form.get("member_id")
        except Exception:
            pass

        try:
            if DOMAIN:
                print(f"✓ Bitrix24 app loaded for {DOMAIN}")

                # ✅ Check if portal is installed in database
                portal = database.get_portal(member_id)
                if not portal:
                    return HTMLResponse(content="""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8" /></head>
<body style="font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#fff5f5">
    <div style="text-align:center;background:white;padding:40px 50px;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,0.08)">
        <div style="font-size:48px">⚠️</div>
        <h2 style="color:#e53e3e;margin:12px 0 8px">App Not Installed Properly</h2>
        <p style="color:#666;font-size:14px">Please reinstall WorkEye from the Bitrix24 Marketplace.</p>
    </div>
</body>
</html>""", status_code=200)

                # ✅ Portal found — redirect to frontend with domain context
                redirect_url = f"https://app.workeye.org/?domain={DOMAIN}&member_id={member_id}"
                return HTMLResponse(content=f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8" />
    <meta http-equiv="refresh" content="0; url={redirect_url}" />
    <script>window.location.href = "{redirect_url}";</script>
</head>
<body style="font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#f0f4ff">
    <p>Loading WorkEye...</p>
</body>
</html>""", status_code=200)

            # ✅ Bitrix validation ping — no params, return plain OK
            return Response(content="OK", status_code=200)

        except Exception as e:
            print(f"❌ Bitrix app launcher error: {e}")
            return HTMLResponse(content="""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8" /></head>
<body style="font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#fff5f5">
    <div style="text-align:center;background:white;padding:40px 50px;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,0.08)">
        <div style="font-size:48px">⚠️</div>
        <h2 style="color:#e53e3e;margin:12px 0 8px">Something Went Wrong</h2>
        <p style="color:#666;font-size:14px">Please close this and try opening the app again.</p>
    </div>
</body>
</html>""", status_code=200)
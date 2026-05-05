"""
bitrix_routes.py
================
All Bitrix24 OAuth and integration endpoints
Rewritten to match working reference pattern:
- POST /install → saves portal, returns JS redirect HTML
- GET  /install → returns JS redirect HTML
- POST /uninstall → deletes portal, returns OK
- ALL  /app → redirects to frontend with params
"""

from fastapi import FastAPI, Request
from fastapi.responses import Response, HTMLResponse
from typing import Optional
import database

# ✅ Your frontend URL — change this if needed
FRONTEND_URL = "https://app.workeye.org"


def setup_bitrix_routes(app: FastAPI):
    """
    Setup all Bitrix24 endpoints on the FastAPI app
    Call this in main.py to register routes
    """

    # ── POST /bitrix/install → Bitrix Marketplace install ─────────────────────
    @app.post("/bitrix/install")
    async def bitrix_install_post(request: Request):
        try:
            form = await request.form()
            print("📥 /install body:", dict(form))

            AUTH_ID      = form.get("AUTH_ID")
            REFRESH_ID   = form.get("REFRESH_ID")
            member_id    = form.get("member_id")
            DOMAIN       = form.get("DOMAIN") or ""
            AUTH_EXPIRES = int(form.get("AUTH_EXPIRES") or 3600)

            if not AUTH_ID or not member_id:
                return HTMLResponse(content=f"""
                    <html><body><script>
                        window.location.href = "{FRONTEND_URL}";
                    </script></body></html>
                """)

            # ✅ Save portal to database
            database.save_portal(
                member_id     = member_id,
                domain        = DOMAIN,
                access_token  = AUTH_ID,
                refresh_token = REFRESH_ID,
                expires_in    = AUTH_EXPIRES
            )

            print(f"✅ Portal saved: {member_id}")

            # ✅ Return JS redirect — exactly like the reference code
            return HTMLResponse(content=f"""
                <html><body><script>
                    window.location.href = "{FRONTEND_URL}/?domain={DOMAIN}&member_id={member_id}&installed=true";
                </script></body></html>
            """)

        except Exception as e:
            print(f"❌ /install error: {e}")
            return HTMLResponse(content=f"""
                <html><body><script>
                    window.location.href = "{FRONTEND_URL}";
                </script></body></html>
            """, status_code=500)


    # ── GET /bitrix/install → validation ping from Bitrix ─────────────────────
    @app.get("/bitrix/install")
    async def bitrix_install_get():
        # ✅ Exactly like reference — just redirect to frontend
        return HTMLResponse(content=f"""
            <html><body><script>
                window.location.href = "{FRONTEND_URL}";
            </script></body></html>
        """)


    # ── POST /bitrix/uninstall → Bitrix uninstall webhook ─────────────────────
    @app.post("/bitrix/uninstall")
    async def bitrix_uninstall(request: Request):
        try:
            form = await request.form()
            member_id = form.get("member_id")

            if member_id:
                database.delete_portal(member_id)
                print(f"🗑️ Uninstalled: {member_id}")

            return Response(content="OK", status_code=200)

        except Exception:
            return Response(content="OK", status_code=200)


    # ── ALL /bitrix/app → App launcher from inside Bitrix sidebar ─────────────
    @app.get("/bitrix/app")
    @app.post("/bitrix/app")
    async def bitrix_app_launcher(request: Request):
        try:
            # Merge query params + form body — exactly like reference
            params = dict(request.query_params)

            try:
                form = await request.form()
                params.update(dict(form))
            except Exception:
                pass

            DOMAIN    = params.get("DOMAIN", "")
            member_id = params.get("member_id", "")

            print(f"✓ Bitrix24 app loaded for {DOMAIN}")

            # ✅ Build redirect URL with all params — exactly like reference
            redirect_url = f"{FRONTEND_URL}/?domain={DOMAIN}&member_id={member_id}"

            return HTMLResponse(content=f"""
                <html><body><script>
                    window.location.href = "{redirect_url}";
                </script></body></html>
            """)

        except Exception:
            return HTMLResponse(content=f"""
                <html><body><script>
                    window.location.href = "{FRONTEND_URL}";
                </script></body></html>
            """)
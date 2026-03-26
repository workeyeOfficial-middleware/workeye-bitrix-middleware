"""
bitrix_routes.py
================
All Bitrix24 OAuth and integration endpoints
Separated from main WorkEye app logic

This keeps Bitrix code isolated and easy to maintain

CHANGES FROM ORIGINAL:
- Filled in TODO: Save to database on install  → uses database.py save_portal()
- Filled in TODO: Delete from database on uninstall → uses database.py delete_portal()
- Everything else is exactly the same
"""

from fastapi import FastAPI
from fastapi.responses import Response
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
        2. Save to database ✅ NOW IMPLEMENTED
        3. Return "OK" to confirm
        """
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
        2. Delete all app data for this portal ✅ NOW IMPLEMENTED
        3. Return "OK" to confirm
        """
        try:
            if member_id:
                print(f"✓ Bitrix24 app uninstalled for {member_id}")

                # ✅ Delete portal tokens from database
                database.delete_portal(member_id)

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
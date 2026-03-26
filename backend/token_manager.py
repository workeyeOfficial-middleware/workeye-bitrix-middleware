"""
token_manager.py
================
Handles auto-refreshing of Bitrix24 access tokens.

WHY THIS IS NEEDED:
- Bitrix24 access tokens expire every 1 hour
- If token expires, all API calls will fail with 401 error
- This file automatically gets a new token using the refresh_token
- Your app never breaks mid-session

HOW IT WORKS:
1. Before making any API call, check if token is expired
2. If expired → call Bitrix24 to get new tokens using refresh_token
3. Save new tokens to database
4. Return fresh access_token
5. Make the API call with fresh token

USED BY:
- bitrix_oauth.py → calls get_valid_token() before every API call
"""

import requests
import os
from database import get_portal, update_tokens, is_token_expired

# Your app's Client ID and Client Secret from Bitrix24 Partner Cabinet
# Set these in your Render environment variables
CLIENT_ID     = os.getenv("BITRIX_CLIENT_ID")
CLIENT_SECRET = os.getenv("BITRIX_CLIENT_SECRET")

# Bitrix24 OAuth token refresh URL
BITRIX_OAUTH_URL = "https://oauth.bitrix.info/oauth/token/"


# =========================
# MAIN FUNCTION
# Get a valid (non-expired) token for a portal
# =========================
def get_valid_token(member_id: str) -> str:
    """
    Returns a valid access_token for the given portal.
    Automatically refreshes if expired.

    Args:
        member_id → Bitrix24 portal unique ID

    Returns:
        access_token string ready to use in API calls

    Raises:
        Exception if portal not found or refresh fails
    """

    # Step 1 — Get portal from database
    portal = get_portal(member_id)
    if not portal:
        raise Exception(f"[TokenManager] Portal not found: {member_id}. App may not be installed.")

    # Step 2 — Check if token is still valid
    if not is_token_expired(member_id):
        print(f"[TokenManager] ✅ Token still valid for {member_id}")
        return portal["access_token"]

    # Step 3 — Token expired, refresh it
    print(f"[TokenManager] 🔄 Token expired for {member_id}, refreshing...")
    new_tokens = _refresh_token(portal["refresh_token"], portal["domain"])

    # Step 4 — Save new tokens to database
    update_tokens(
        member_id     = member_id,
        access_token  = new_tokens["access_token"],
        refresh_token = new_tokens["refresh_token"],
        expires_in    = new_tokens.get("expires_in", 3600)
    )

    print(f"[TokenManager] ✅ Token refreshed successfully for {member_id}")
    return new_tokens["access_token"]


# =========================
# REFRESH — Call Bitrix24 to get new tokens
# =========================
def _refresh_token(refresh_token: str, domain: str) -> dict:
    """
    Calls Bitrix24 OAuth server to exchange refresh_token for new tokens.

    Args:
        refresh_token → saved refresh token from database
        domain        → portal domain e.g. company.bitrix24.com

    Returns:
        {
            "access_token": "...",
            "refresh_token": "...",
            "expires_in": 3600
        }

    Raises:
        Exception if refresh fails
    """

    if not CLIENT_ID or not CLIENT_SECRET:
        raise Exception(
            "[TokenManager] BITRIX_CLIENT_ID or BITRIX_CLIENT_SECRET not set. "
            "Add them to your Render environment variables."
        )

    try:
        response = requests.post(
            BITRIX_OAUTH_URL,
            params={
                "grant_type":    "refresh_token",
                "client_id":     CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": refresh_token,
            },
            timeout=15
        )

        print(f"[TokenManager] Refresh response status: {response.status_code}")

        if response.status_code != 200:
            raise Exception(
                f"[TokenManager] Refresh failed: {response.status_code} - {response.text[:200]}"
            )

        data = response.json()

        # Check we got valid tokens back
        if not data.get("access_token"):
            raise Exception(f"[TokenManager] No access_token in refresh response: {data}")

        return {
            "access_token":  data["access_token"],
            "refresh_token": data.get("refresh_token", refresh_token),  # Bitrix sometimes returns same refresh token
            "expires_in":    data.get("expires_in", 3600)
        }

    except requests.exceptions.Timeout:
        raise Exception("[TokenManager] Bitrix24 OAuth server timed out during refresh.")
    except requests.exceptions.RequestException as e:
        raise Exception(f"[TokenManager] Network error during token refresh: {e}")


# =========================
# HELPER — Get portal domain
# =========================
def get_portal_domain(member_id: str) -> str:
    """
    Returns the domain for a portal.
    Useful when you need to build the Bitrix24 API URL.

    Args:
        member_id → Bitrix24 portal unique ID

    Returns:
        domain string e.g. "company.bitrix24.com"
    """
    portal = get_portal(member_id)
    if not portal:
        raise Exception(f"[TokenManager] Portal not found: {member_id}")
    return portal["domain"]
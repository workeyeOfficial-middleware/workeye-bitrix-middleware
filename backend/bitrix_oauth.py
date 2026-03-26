"""
bitrix_oauth.py
===============
Makes API calls to Bitrix24 using saved OAuth tokens.

WHY THIS FILE EXISTS:
- bitrix_service.py uses a hardcoded webhook (only YOUR portal)
- This file uses saved tokens from database (works for EVERY customer)
- Every customer who installs your app has their own portal
- This file handles talking to each customer's portal correctly

HOW IT WORKS:
1. You pass member_id (customer's portal ID)
2. It gets their valid token from token_manager.py
3. It builds the correct API URL for their portal
4. It makes the API call and returns the result

DIFFERENCE FROM bitrix_service.py:
- bitrix_service.py  → hardcoded webhook → only YOUR portal
- bitrix_oauth.py    → per customer token → ALL customer portals

USED BY:
- bitrix_routes.py → when app is installed/uninstalled
- main.py          → when syncing data to a customer's portal
"""

import requests
from token_manager import get_valid_token, get_portal_domain
from database import get_portal


# =========================
# CORE API CALL
# =========================
def call_bitrix(member_id: str, method: str, params: dict = None) -> dict:
    """
    Makes an API call to a customer's Bitrix24 portal.

    Args:
        member_id → customer's Bitrix24 portal unique ID
        method    → Bitrix24 API method e.g. "disk.folder.getchildren"
        params    → dict of parameters to send

    Returns:
        dict with API response

    Example:
        result = call_bitrix("12345", "disk.folder.getchildren", {"id": "3"})
    """

    # Step 1 — Get valid token (auto refreshes if expired)
    access_token = get_valid_token(member_id)

    # Step 2 — Get their portal domain
    domain = get_portal_domain(member_id)

    # Step 3 — Build API URL
    # Bitrix24 REST API URL format:
    # https://DOMAIN/rest/METHOD?auth=ACCESS_TOKEN
    api_url = f"https://{domain}/rest/{method}.json"

    # Step 4 — Make the API call
    try:
        response = requests.post(
            api_url,
            json=params or {},
            params={"auth": access_token},
            timeout=15
        )

        print(f"[BitrixOAuth] {method} → {response.status_code} for portal {member_id}")

        if response.status_code == 401:
            raise Exception(f"[BitrixOAuth] Unauthorized — token may be invalid for {member_id}")

        if response.status_code != 200:
            raise Exception(f"[BitrixOAuth] API error {response.status_code}: {response.text[:200]}")

        return response.json()

    except requests.exceptions.Timeout:
        raise Exception(f"[BitrixOAuth] Timeout calling {method} for portal {member_id}")
    except requests.exceptions.RequestException as e:
        raise Exception(f"[BitrixOAuth] Network error: {e}")


# =========================
# GET OR CREATE FOLDER IN DRIVE
# =========================
def get_or_create_folder(member_id: str, folder_name: str = "WorkEye Reports") -> str:
    """
    Finds or creates a folder in the customer's Bitrix24 Shared Drive.

    Args:
        member_id   → customer's portal ID
        folder_name → name of folder to find/create (default: WorkEye Reports)

    Returns:
        folder ID string
    """

    SHARED_DRIVE_ID = "3"  # Bitrix24 Shared Drive ID

    # Check if folder already exists
    result = call_bitrix(member_id, "disk.folder.getchildren", {"id": SHARED_DRIVE_ID})
    items = result.get("result", [])

    for item in items:
        if item.get("NAME") == folder_name and item.get("TYPE") == "folder":
            print(f"[BitrixOAuth] Found existing folder '{folder_name}' ID: {item['ID']}")
            return item["ID"]

    # Create folder if not found
    result = call_bitrix(
        member_id,
        "disk.folder.addsubfolder",
        {
            "id":   SHARED_DRIVE_ID,
            "data": {"NAME": folder_name}
        }
    )
    folder = result.get("result", {})
    folder_id = folder.get("ID")
    print(f"[BitrixOAuth] Created folder '{folder_name}' ID: {folder_id}")
    return folder_id


# =========================
# SAVE FILE TO DRIVE
# =========================
def save_file_to_drive(member_id: str, filename: str, content: str) -> dict:
    """
    Saves a text file to the customer's Bitrix24 Shared Drive.
    File will appear at: Bitrix24 → Drive → Shared Drive → WorkEye Reports

    Args:
        member_id → customer's portal ID
        filename  → e.g. "Attendance_Report_2026-03-25.txt"
        content   → text content of the file

    Returns:
        {
            "success": True/False,
            "file_id": "...",
            "url": "..."
        }
    """
    import base64

    # Step 1 — Get or create WorkEye Reports folder
    folder_id = get_or_create_folder(member_id)
    if not folder_id:
        return {"success": False, "error": "Could not get or create folder"}

    # Step 2 — Encode content to base64 (Bitrix24 requires this)
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    # Step 3 — Upload file
    result = call_bitrix(
        member_id,
        "disk.folder.uploadfile",
        {
            "id":          folder_id,
            "data":        {"NAME": filename},
            "fileContent": encoded
        }
    )

    file_result = result.get("result", {})
    file_id     = file_result.get("ID")
    detail_url  = file_result.get("DETAIL_URL", "")

    if file_id:
        print(f"[BitrixOAuth] ✅ File saved: {filename} (ID: {file_id})")
        return {"success": True, "file_id": file_id, "url": detail_url}
    else:
        print(f"[BitrixOAuth] ❌ File save failed: {result}")
        return {"success": False, "error": str(result)}


# =========================
# CHECK IF PORTAL IS CONNECTED
# =========================
def is_portal_connected(member_id: str) -> bool:
    """
    Checks if a portal is connected and tokens are saved.

    Args:
        member_id → customer's portal ID

    Returns:
        True if connected, False if not
    """
    portal = get_portal(member_id)
    return portal is not None


# =========================
# GET PORTAL INFO
# =========================
def get_portal_info(member_id: str) -> dict:
    """
    Returns basic info about a connected portal.

    Args:
        member_id → customer's portal ID

    Returns:
        {
            "member_id": "...",
            "domain": "...",
            "connected": True/False
        }
    """
    portal = get_portal(member_id)
    if not portal:
        return {"member_id": member_id, "connected": False}

    return {
        "member_id": portal["member_id"],
        "domain":    portal["domain"],
        "connected": True,
        "installed_at": portal["created_at"]
    }
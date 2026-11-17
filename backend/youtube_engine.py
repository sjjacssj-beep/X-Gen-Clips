import json
import logging
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, Callable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
import googleapiclient.discovery
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger("xgenclips.youtube")

BASE_DIR = Path(__file__).resolve().parent.parent
SECRETS_DIR = BASE_DIR / "secrets"
CLIENT_SECRET_FILE = SECRETS_DIR / "client_secret.json"
TOKEN_FILE = SECRETS_DIR / "token.json"

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
LOCAL_PORT = 8088

# Active auth thread tracking
_auth_thread = None
_auth_in_progress = False

def is_client_secret_present() -> bool:
    """Checks if client_secret.json is installed in secrets/."""
    return CLIENT_SECRET_FILE.exists() and CLIENT_SECRET_FILE.stat().st_size > 50

def get_credentials() -> Tuple[Optional[Credentials], str]:
    """
    Loads saved credentials from secrets/token.json.
    Automatically refreshes expired token if refresh_token is present.
    Returns (credentials, status_code_or_message).
    """
    if not is_client_secret_present():
        return None, "no_client_secret"

    if not TOKEN_FILE.exists():
        return None, "not_connected"

    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    except Exception as e:
        logger.warning(f"Failed to read token.json: {e}")
        return None, "invalid_token"

    if creds and creds.valid:
        return creds, "connected"

    if creds and creds.expired and creds.refresh_token:
        try:
            logger.info("YouTube token expired, attempting automatic refresh...")
            creds.refresh(Request())
            # Save refreshed credentials
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
            return creds, "connected"
        except Exception as e:
            logger.error(f"Failed to refresh YouTube token: {e}")
            return None, "login_expired"

    return None, "not_connected"

def check_youtube_status() -> Dict[str, Any]:
    """Returns clean status dictionary for frontend settings badge."""
    global _auth_in_progress
    if not is_client_secret_present():
        return {
            "configured": False,
            "connected": False,
            "in_progress": False,
            "status": "missing_secret",
            "message": "client_secret.json nahi mila. Project ke secrets/ folder mein rakhein."
        }

    if _auth_in_progress:
        return {
            "configured": True,
            "connected": False,
            "in_progress": True,
            "status": "authenticating",
            "message": "Browser mein Google login chal raha hai... Kripya permission allow karein."
        }

    creds, reason = get_credentials()
    if creds and creds.valid:
        return {
            "configured": True,
            "connected": True,
            "in_progress": False,
            "status": "connected",
            "message": "✓ YouTube account juda hua hai (Ready to upload)."
        }
    elif reason == "login_expired":
        return {
            "configured": True,
            "connected": False,
            "in_progress": False,
            "status": "expired",
            "message": "YouTube login expire ho gaya hai. Kripya 'Dobara jodo' par click karein."
        }
    else:
        return {
            "configured": True,
            "connected": False,
            "in_progress": False,
            "status": "not_connected",
            "message": "YouTube connected nahi hai. 'YouTube jodo' button dabayein."
        }

def start_interactive_auth() -> Dict[str, Any]:
    """
    Spawns background OAuth Desktop flow with local server callback.
    Opens the default browser for Google consent.
    """
    global _auth_thread, _auth_in_progress

    if not is_client_secret_present():
        raise FileNotFoundError("secrets/client_secret.json file nahi mili! Pehle file rakhein.")

    if _auth_in_progress:
        return {"status": "already_running", "message": "Login pehle se background mein chal raha hai. Browser check karein."}

    def _auth_worker():
        global _auth_in_progress
        _auth_in_progress = True
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_FILE),
                scopes=SCOPES
            )
            # Run local server on designated port with browser prompt
            creds = flow.run_local_server(
                port=LOCAL_PORT,
                prompt="consent",
                authorization_prompt_message="Google authorization ke liye browser window khul rahi hai...",
                success_message="<h1>✓ Authentication Successful!</h1><p>Aapka YouTube account X Gen Clips se jud gaya hai. Ab aap is tab ko band kar sakte hain.</p>"
            )
            if creds:
                SECRETS_DIR.mkdir(parents=True, exist_ok=True)
                TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
                logger.info("YouTube token.json successfully saved!")
        except Exception as e:
            logger.error(f"Error during OAuth flow: {e}")
        finally:
            _auth_in_progress = False

    _auth_thread = threading.Thread(target=_auth_worker, daemon=True)
    _auth_thread.start()

    return {
        "status": "started",
        "message": "Google Login browser mein open kiya ja raha hai. Apne test account se login karke 'Continue/Allow' karein."
    }

def disconnect_youtube() -> Dict[str, Any]:
    """Deletes token.json to disconnect current account."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink(missing_ok=True)
    return {"status": "disconnected", "message": "YouTube account safely disconnect ho gaya hai."}

def get_youtube_service():
    """Builds and returns authenticated YouTube Resource."""
    creds, reason = get_credentials()
    if not creds:
        if reason == "login_expired":
            raise PermissionError("YouTube login expire ho chuka hai. Kripya Settings mein 'Dobara jodo' dabayein.")
        raise PermissionError("YouTube account juda hua nahi hai. Kripya Settings se 'YouTube jodo' par click karein.")

    return googleapiclient.discovery.build("youtube", "v3", credentials=creds, cache_discovery=False)

def format_error_hinglish(error_obj: Exception) -> str:
    """Translates raw Google API errors into clear, actionable Hinglish explanations."""
    err_str = str(error_obj).lower()

    if isinstance(error_obj, HttpError):
        try:
            content = json.loads(error_obj.content.decode("utf-8"))
            errors = content.get("error", {}).get("errors", [])
            if errors:
                reason = errors[0].get("reason", "")
                if reason == "quotaExceeded":
                    return "YouTube Data API ki daily upload limit (10,000 units/day) exceed ho gayi hai. Kal quota reset hone ke baad upload hoga."
                elif reason == "uploadLimitExceeded":
                    return "Aapke YouTube channel ki 24-ghante ki video upload limit reach ho gayi hai. Kripya kal dobara koshish karein."
                elif reason == "accessNotConfigured":
                    return "Google Cloud Console mein 'YouTube Data API v3' enable nahi hai. API library se enable karein."
                elif reason == "invalid_grant":
                    return "Aapka YouTube login expire ho gaya hai. Kripya Settings mein 'Dobara jodo' dabayein."
        except Exception:
            pass

    if "quotaexceeded" in err_str:
        return "YouTube Data API quota exceed ho gaya hai. Daily limit khatam ho chuki hai."
    elif "uploadlimitexceeded" in err_str:
        return "Channel ki daily upload limit reach ho gayi hai. Thoda wait karein."
    elif "invalid_grant" in err_str or "expired" in err_str:
        return "YouTube login expire ho chuka hai. Settings se dobara connect karein."
    elif "accessdenied" in err_str or "unauthorized" in err_str or "403" in err_str:
        return "Permission issue: Ensure karein ki aapka Gmail account Google Cloud Console ke 'OAuth consent screen -> Test users' mein add hai."

    return f"YouTube upload error: {str(error_obj)[:180]}"

def upload_clip_to_youtube(
    video_path: Path,
    title: str,
    description: str,
    hashtags: Optional[list] = None,
    privacy_status: str = "private",
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> Dict[str, Any]:
    """
    Executes a resumable video upload to YouTube using chunked MediaFileUpload.
    Always uses privacyStatus='private' (default), categoryId='22', selfDeclaredMadeForKids=False.
    Checks for Google 'locked private' state after upload.
    """
    if not video_path.exists():
        raise FileNotFoundError(f"Video file nahi mili: {video_path.name}")

    youtube = get_youtube_service()

    # Sanitize Title (Max 100 chars, no < >)
    clean_title = title.replace("<", "").replace(">", "").strip()
    if not clean_title:
        clean_title = f"Clip - {video_path.stem}"
    if len(clean_title) > 95:
        clean_title = clean_title[:92] + "..."

    # Sanitize Tags
    tag_list = []
    if hashtags:
        for t in hashtags:
            clean_tag = t.replace("#", "").strip()
            if clean_tag and len(clean_tag) < 30 and clean_tag not in tag_list:
                tag_list.append(clean_tag)
    if not tag_list:
        tag_list = ["Shorts", "Viral", "Trending", "Reels"]

    # Build snippet and status
    body = {
        "snippet": {
            "title": clean_title,
            "description": description or f"{clean_title}\n\nUploaded via X Gen Clips.",
            "tags": tag_list[:15],
            "categoryId": "22",  # People & Blogs
            "defaultLanguage": "hi",
            "defaultAudioLanguage": "hi"
        },
        "status": {
            "privacyStatus": privacy_status,  # Default: private
            "selfDeclaredMadeForKids": False,
            "embeddable": True
        }
    }

    # Resumable upload in 2MB chunks
    chunk_size = 2 * 1024 * 1024
    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        chunksize=chunk_size,
        resumable=True
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None
    if progress_callback:
        progress_callback(5, "YouTube upload shuru kar rahe hain...")

    while response is None:
        status, response = request.next_chunk()
        if status and progress_callback:
            pct = int(status.progress() * 100)
            progress_callback(pct, f"Uploading to YouTube... ({pct}%)")

    video_id = response.get("id")
    if not video_id:
        raise ValueError("Upload complete hua par video ID nahi mili.")

    video_url = f"https://youtu.be/{video_id}"
    youtube_studio_url = f"https://studio.youtube.com/video/{video_id}/edit"

    # Post-Upload Verification: Check for "Locked Private"
    is_locked_private = False
    warning_message = None
    try:
        vid_query = youtube.videos().list(part="status", id=video_id).execute()
        items = vid_query.get("items", [])
        if items:
            v_status = items[0].get("status", {})
            rejection = v_status.get("rejectionReason")
            # If Google locked it private due to unverified developer credentials
            if rejection or (v_status.get("privacyStatus") == "private" and v_status.get("uploadStatus") == "rejected"):
                is_locked_private = True
                warning_message = "Video Google ke unverified developer app policy ke karan 'Locked Private' mark hui hai. Ye video sirf aapke test Gmail account ko dikhegi."
    except Exception as e:
        logger.warning(f"Could not check locked private status: {e}")

    result = {
        "status": "success",
        "video_id": video_id,
        "video_url": video_url,
        "studio_url": youtube_studio_url,
        "title": clean_title,
        "privacy": privacy_status,
        "is_locked_private": is_locked_private,
        "warning_message": warning_message,
        "message": f"✓ Video successfully YouTube par upload ho gayi! ({video_url})"
    }

    if is_locked_private and warning_message:
        result["message"] += f" ⚠ Note: {warning_message}"

    return result

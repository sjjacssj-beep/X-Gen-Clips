import json
import logging
import os
import shutil
import sys
import threading
import time
import webbrowser
import wsgiref.simple_server
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, Callable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import (
    InstalledAppFlow,
    _ExclusiveWSGIServer,
    _WSGIRequestHandler
)
import wsgiref.util

class _HTMLRedirectWSGIApp:
    """WSGI app to handle the authorization redirect with Content-Type: text/html; charset=utf-8."""
    def __init__(self, html_content: str):
        self.last_request_uri = None
        self._html_content = html_content

    def __call__(self, environ, start_response):
        start_response("200 OK", [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Cache-Control", "no-cache, no-store, must-revalidate")
        ])
        self.last_request_uri = wsgiref.util.request_uri(environ)
        return [self._html_content.encode("utf-8")]

def get_callback_html_page() -> str:
    """Returns the branded X Gen Clips success callback page with countdown and instant sync."""
    return """<!DOCTYPE html>
<html lang="hi">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>X Gen Clips — YouTube Connected!</title>
    <style>
        :root {
            --bg-deep: #070B14;
            --bg-card: #0F172A;
            --border-card: rgba(56, 189, 248, 0.22);
            --orange: #D97706;
            --orange-bright: #F59E0B;
            --sky: #38BDF8;
            --green: #10B981;
            --text-main: #F8FAFC;
            --text-muted: #94A3B8;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: var(--bg-deep);
            background-image: 
                radial-gradient(circle at 50% 20%, rgba(56, 189, 248, 0.12) 0%, transparent 55%),
                radial-gradient(circle at 80% 80%, rgba(217, 119, 6, 0.08) 0%, transparent 50%);
            color: var(--text-main);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            max-width: 540px;
            width: 100%;
            border-radius: 24px;
            padding: 44px 36px;
            text-align: center;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6), 0 0 40px rgba(56, 189, 248, 0.1);
            position: relative;
            overflow: hidden;
        }
        .card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; height: 4px;
            background: linear-gradient(90deg, var(--orange), var(--sky));
        }
        .brand {
            font-size: 26px;
            font-weight: 800;
            letter-spacing: -0.5px;
            margin-bottom: 22px;
            display: inline-block;
        }
        .brand-x {
            color: var(--orange);
            font-weight: 900;
            font-size: 30px;
            text-shadow: 0 0 16px rgba(217, 119, 6, 0.5);
        }
        .brand-text {
            color: var(--text-main);
        }
        .badge-pill {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(16, 185, 129, 0.15);
            border: 1px solid rgba(16, 185, 129, 0.35);
            color: #34D399;
            padding: 6px 18px;
            border-radius: 9999px;
            font-size: 14px;
            font-weight: 700;
            margin-bottom: 20px;
        }
        .badge-dot {
            width: 8px;
            height: 8px;
            background: #10B981;
            border-radius: 50%;
            box-shadow: 0 0 10px #10B981;
        }
        h1 {
            font-size: 24px;
            font-weight: 800;
            color: var(--text-main);
            margin-bottom: 12px;
        }
        p {
            color: var(--text-muted);
            font-size: 15px;
            line-height: 1.6;
            margin-bottom: 24px;
        }
        .countdown-box {
            background: rgba(56, 189, 248, 0.08);
            border: 1px solid rgba(56, 189, 248, 0.18);
            border-radius: 12px;
            padding: 12px 18px;
            font-size: 14px;
            color: var(--sky);
            margin-bottom: 28px;
            font-weight: 600;
        }
        .countdown-num {
            font-size: 18px;
            font-weight: 800;
            color: var(--orange-bright);
        }
        .btn-group {
            display: flex;
            gap: 12px;
            justify-content: center;
            flex-wrap: wrap;
        }
        .btn {
            padding: 12px 22px;
            border-radius: 12px;
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            border: none;
        }
        .btn-primary {
            background: linear-gradient(135deg, var(--orange), #B45309);
            color: #FFFFFF;
            box-shadow: 0 6px 18px rgba(217, 119, 6, 0.35);
        }
        .btn-primary:hover {
            opacity: 0.95;
            transform: translateY(-1px);
        }
        .btn-secondary {
            background: rgba(255, 255, 255, 0.06);
            color: var(--text-main);
            border: 1px solid rgba(255, 255, 255, 0.15);
        }
        .btn-secondary:hover {
            background: rgba(255, 255, 255, 0.12);
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="brand">
            <span class="brand-x">X</span> <span class="brand-text">Gen Clips</span>
        </div>
        <div>
            <div class="badge-pill">
                <span class="badge-dot"></span>
                YouTube Connected
            </div>
        </div>
        <h1>YouTube Safalta Se Jud Gaya!</h1>
        <p>Aapka Google account X Gen Clips se jud chuka hai. Ab aap apni clips bina kisi jhanjhat direct YouTube par upload kar sakte hain.</p>
        
        <div class="countdown-box">
            ⏱️ <span id="sec" class="countdown-num">3</span> second mein Settings page par le ja rahe hain...
        </div>

        <div class="btn-group">
            <button type="button" class="btn btn-secondary" onclick="closeThisTab()">
                ✖ Is Tab Ko Band Karo
            </button>
            <a href="http://localhost:9999/#settings" class="btn btn-primary" onclick="redirectToApp(event)">
                ⚙️ Settings Mein Jayein
            </a>
        </div>
    </div>

    <script>
        // Notify opener / other tabs immediately
        try {
            if (window.opener && !window.opener.closed) {
                if (window.opener.App) {
                    window.opener.App.checkYouTubeStatus();
                    window.opener.App.switchTab('settings');
                }
            }
        } catch (e) {}

        try {
            localStorage.setItem('xgenclips_youtube_auth_done', Date.now().toString());
            const bc = new BroadcastChannel('xgenclips_channel');
            bc.postMessage({ type: 'youtube_connected' });
        } catch (e) {}

        function closeThisTab() {
            window.close();
            setTimeout(() => {
                window.location.href = 'http://localhost:9999/#settings';
            }, 300);
        }

        function redirectToApp(e) {
            if (e) e.preventDefault();
            window.location.href = 'http://localhost:9999/#settings';
        }

        // 3-second auto-redirect countdown
        let countdown = 3;
        const countdownTimer = setInterval(() => {
            countdown--;
            const el = document.getElementById('sec');
            if (el) el.innerText = countdown;
            if (countdown <= 0) {
                clearInterval(countdownTimer);
                window.location.href = 'http://localhost:9999/#settings';
            }
        }, 1000);
    </script>
</body>
</html>"""
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
_current_auth_url = None
_local_server_instance = None

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
    global _auth_in_progress, _current_auth_url
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
            "auth_url": _current_auth_url,
            "status": "authenticating",
            "message": "Browser mein Google login chal raha hai. Kripya niche diye link par click karein."
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

def cancel_auth() -> Dict[str, Any]:
    """Cancels any in-progress auth server cleanly."""
    global _auth_in_progress, _current_auth_url, _local_server_instance
    if _local_server_instance:
        try:
            _local_server_instance.server_close()
        except Exception:
            pass
    _auth_in_progress = False
    _current_auth_url = None
    _local_server_instance = None
    return {"status": "cancelled", "message": "Login flow cancel kar diya gaya hai."}

def start_interactive_auth() -> Dict[str, Any]:
    """
    Spawns background OAuth Desktop flow with local server callback.
    Generates auth_url immediately and returns it so frontend can window.open it.
    """
    global _auth_thread, _auth_in_progress, _current_auth_url, _local_server_instance

    if not is_client_secret_present():
        raise FileNotFoundError("secrets/client_secret.json file nahi mili! Pehle file rakhein.")

    # Clean up any stale server
    if _local_server_instance:
        try:
            _local_server_instance.server_close()
        except Exception:
            pass

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRET_FILE),
        scopes=SCOPES
    )
    wsgi_app = _HTMLRedirectWSGIApp(get_callback_html_page())
    server = wsgiref.simple_server.make_server(
        'localhost',
        LOCAL_PORT,
        wsgi_app,
        server_class=_ExclusiveWSGIServer,
        handler_class=_WSGIRequestHandler
    )
    flow.redirect_uri = f"http://localhost:{server.server_port}/"
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")

    _current_auth_url = auth_url
    _auth_in_progress = True
    _local_server_instance = server

    # Try launching desktop browser in foreground via Windows shell
    try:
        os.startfile(auth_url)
    except Exception:
        try:
            webbrowser.open(auth_url, new=1, autoraise=True)
        except Exception:
            pass

    def _auth_worker():
        global _auth_in_progress, _current_auth_url, _local_server_instance
        try:
            server.timeout = 300  # 5 minutes
            server.handle_request()
            if wsgi_app.last_request_uri:
                auth_resp = wsgi_app.last_request_uri.replace("http://", "https://")
                flow.fetch_token(authorization_response=auth_resp)
                creds = flow.credentials
                if creds:
                    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
                    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
                    logger.info("YouTube token.json successfully saved!")
        except Exception as e:
            logger.error(f"Error during OAuth callback: {e}")
        finally:
            try:
                server.server_close()
            except Exception:
                pass
            _auth_in_progress = False
            _current_auth_url = None
            _local_server_instance = None

    _auth_thread = threading.Thread(target=_auth_worker, daemon=True)
    _auth_thread.start()

    return {
        "status": "started",
        "auth_url": auth_url,
        "message": "Google Login URL tayar ho gaya hai. Browser mein sign in karke 'Allow' karein."
    }

def disconnect_youtube() -> Dict[str, Any]:
    """Deletes token.json to disconnect current account."""
    cancel_auth()
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

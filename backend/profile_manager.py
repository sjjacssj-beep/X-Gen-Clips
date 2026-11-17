import hashlib
import json
import logging
import os
import shutil
import sqlite3
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("xgenclips.profiles")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PROFILES_DIR = DATA_DIR / "profiles"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_PROFILE_ID = "default"

def hash_pin(pin: str) -> str:
    """Generates salted SHA256 hash for 4-digit PIN."""
    salt = "xgenclips_secure_pin_salt_2026"
    return hashlib.sha256(f"{salt}_{pin}".encode("utf-8")).hexdigest()

class ProfileManager:
    def __init__(self):
        self.ensure_default_profile()

    def get_profile_dir(self, profile_id: str) -> Path:
        clean_id = "".join(c for c in profile_id if c.isalnum() or c in ("-", "_")).lower()
        if not clean_id:
            clean_id = DEFAULT_PROFILE_ID
        pdir = PROFILES_DIR / clean_id
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "outputs").mkdir(parents=True, exist_ok=True)
        (pdir / "secrets").mkdir(parents=True, exist_ok=True)
        return pdir

    def ensure_default_profile(self):
        """Creates the default profile if none exists."""
        def_dir = self.get_profile_dir(DEFAULT_PROFILE_ID)
        meta_file = def_dir / "profile.json"
        if not meta_file.exists():
            meta = {
                "id": DEFAULT_PROFILE_ID,
                "name": "Primary Channel",
                "handle": "@PrimaryChannel",
                "color": "#D97706",
                "pin_hash": "",
                "youtube_channel_name": "",
                "created_at": "2026-11-17"
            }
            meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        
        # Initialize SQLite WAL queue database
        self.init_profile_db(DEFAULT_PROFILE_ID)

    def init_profile_db(self, profile_id: str):
        """Initializes SQLite database with WAL mode for concurrency."""
        pdir = self.get_profile_dir(profile_id)
        db_path = pdir / "queue.db"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_queue (
                    id TEXT PRIMARY KEY,
                    source_url TEXT,
                    source_type TEXT,
                    status TEXT,
                    progress INTEGER,
                    step_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS upload_schedule (
                    clip_id INTEGER PRIMARY KEY,
                    filename TEXT,
                    scheduled_time TIMESTAMP,
                    status TEXT,
                    youtube_video_id TEXT
                );
            """)

    def list_profiles(self) -> List[Dict[str, Any]]:
        """Returns all configured channel profiles."""
        profiles = []
        for pdir in sorted(PROFILES_DIR.iterdir()):
            if pdir.is_dir():
                meta_file = pdir / "profile.json"
                if meta_file.exists():
                    try:
                        m = json.loads(meta_file.read_text(encoding="utf-8"))
                        profiles.append({
                            "id": m.get("id", pdir.name),
                            "name": m.get("name", pdir.name),
                            "handle": m.get("handle", ""),
                            "color": m.get("color", "#38BDF8"),
                            "has_pin": bool(m.get("pin_hash")),
                            "youtube_channel_name": m.get("youtube_channel_name", "")
                        })
                    except Exception:
                        pass
        return profiles

    def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        pdir = self.get_profile_dir(profile_id)
        meta_file = pdir / "profile.json"
        if meta_file.exists():
            return json.loads(meta_file.read_text(encoding="utf-8"))
        return None

    def create_profile(self, name: str, color: str = "#38BDF8", pin: Optional[str] = None) -> Dict[str, Any]:
        """Creates a brand new isolated profile directory & database."""
        pid = name.lower().replace(" ", "-")
        pid = "".join(c for c in pid if c.isalnum() or c == "-")
        if not pid:
            pid = f"profile-{len(self.list_profiles()) + 1}"

        pdir = self.get_profile_dir(pid)
        pin_hash = hash_pin(pin) if pin and len(pin) == 4 else ""
        meta = {
            "id": pid,
            "name": name,
            "handle": f"@{name.replace(' ', '')}",
            "color": color,
            "pin_hash": pin_hash,
            "youtube_channel_name": "",
            "created_at": "2026-11-17"
        }
        (pdir / "profile.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        
        # Clone default settings
        def_settings = BASE_DIR / "settings.json"
        if def_settings.exists():
            shutil.copy2(def_settings, pdir / "settings.json")
        
        self.init_profile_db(pid)
        return meta

    def verify_pin(self, profile_id: str, pin: str) -> bool:
        """Verifies 4-digit PIN for switching profiles."""
        p = self.get_profile(profile_id)
        if not p:
            return False
        stored_hash = p.get("pin_hash", "")
        if not stored_hash:
            return True  # No PIN set
        return stored_hash == hash_pin(pin)

    def set_pin(self, profile_id: str, old_pin: str, new_pin: str) -> bool:
        """Sets or updates 4-digit PIN."""
        pdir = self.get_profile_dir(profile_id)
        meta_file = pdir / "profile.json"
        if not meta_file.exists():
            return False
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        if meta.get("pin_hash") and not self.verify_pin(profile_id, old_pin):
            return False
        meta["pin_hash"] = hash_pin(new_pin) if new_pin and len(new_pin) == 4 else ""
        meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return True

    def export_profile(self, profile_id: str) -> Path:
        """Exports profile configuration, settings and brand kit into a zip archive."""
        pdir = self.get_profile_dir(profile_id)
        export_zip = DATA_DIR / f"profile_backup_{profile_id}.zip"
        with zipfile.ZipFile(export_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for f in ("profile.json", "settings.json", "history.json"):
                fp = pdir / f
                if fp.exists():
                    z.write(fp, arcname=f)
        return export_zip

    def import_profile(self, zip_path: Path) -> Dict[str, Any]:
        """Imports profile from a zip backup archive."""
        with zipfile.ZipFile(zip_path, "r") as z:
            meta_raw = z.read("profile.json").decode("utf-8")
            meta = json.loads(meta_raw)
            pid = meta.get("id", f"import-{int(os.path.getmtime(zip_path))}")
            pdir = self.get_profile_dir(pid)
            z.extractall(pdir)
            self.init_profile_db(pid)
            return meta

# Singleton profile manager
profile_manager = ProfileManager()

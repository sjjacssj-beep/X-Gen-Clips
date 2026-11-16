import asyncio
import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE_DIR / "outputs"
HISTORY_FILE = BASE_DIR / "history.json"
SETTINGS_FILE = BASE_DIR / "settings.json"

class JobQueueManager:
    def __init__(self):
        self.jobs = []
        self.active_job = None
        self.listeners = []
        self.lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.active_processes = []

    def register_process(self, proc):
        with self.lock:
            self.active_processes.append(proc)

    def unregister_process(self, proc):
        with self.lock:
            if proc in self.active_processes:
                self.active_processes.remove(proc)

    def cancel_active_job(self):
        self.cancel_event.set()
        with self.lock:
            for proc in list(self.active_processes):
                try:
                    proc.kill()
                except Exception:
                    pass
            self.active_processes.clear()
            self.active_job = None

    def get_state(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "active_job": self.active_job,
                "is_cancelled": self.cancel_event.is_set(),
                "queue_length": len(self.jobs),
                "queued_jobs": [
                    {"id": j["id"], "url": j["url"], "title": j.get("title", "Queued Video")}
                    for j in self.jobs
                ]
            }

    def broadcast(self, event_type: str, data: Dict[str, Any]):
        msg = f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        with self.lock:
            alive_listeners = []
            for q in self.listeners:
                try:
                    q.put_nowait(msg)
                    alive_listeners.append(q)
                except Exception:
                    pass
            self.listeners = alive_listeners

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=100)
        with self.lock:
            self.listeners.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self.lock:
            if q in self.listeners:
                self.listeners.remove(q)

def load_settings() -> Dict[str, Any]:
    defaults = {
        "user_name": "Creator",
        "model": "gemini-3.5-flash",
        "theme": "dark",
        "auto_render_on_paste": False,
        "auto_open_folder": False,
        "brand_watermark": "",
        "brand_font": "Baloo 2",
        "brand_color": "hormozi",
        "daily_quota_used": 3
    }
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            defaults.update(saved)
        except Exception:
            pass
    return defaults

def save_settings(new_settings: Dict[str, Any]):
    curr = load_settings()
    curr.update(new_settings)
    SETTINGS_FILE.write_text(json.dumps(curr, indent=2, ensure_ascii=False), encoding="utf-8")
    return curr

def load_history() -> List[Dict[str, Any]]:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []

def save_to_history(record: Dict[str, Any]):
    hist = load_history()
    # Filter out duplicate by id
    hist = [h for h in hist if h.get("id") != record.get("id")]
    hist.insert(0, record)
    # Keep last 50
    hist = hist[:50]
    HISTORY_FILE.write_text(json.dumps(hist, indent=2, ensure_ascii=False), encoding="utf-8")

def clear_workspace() -> Dict[str, Any]:
    count = 0
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    for f in OUTPUTS_DIR.iterdir():
        if f.is_file():
            try:
                f.unlink(missing_ok=True)
                count += 1
            except Exception:
                pass
    if HISTORY_FILE.exists():
        HISTORY_FILE.write_text("[]", encoding="utf-8")
    return {"cleared_files": count}

job_manager = JobQueueManager()

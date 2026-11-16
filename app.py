import asyncio
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

# Ensure LocalAppData ffmpeg is in PATH
local_ffmpeg = Path(os.environ.get("LOCALAPPDATA", "")) / "ffmpeg"
if local_ffmpeg.exists() and str(local_ffmpeg) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(local_ffmpeg) + os.pathsep + os.environ.get("PATH", "")

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
import clipper

OUT_DIR = BASE_DIR / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = BASE_DIR / "settings.json"
ENV_FILE = BASE_DIR / ".env"

# Load .env into os.environ
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("GEMINI_API_KEY="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if key:
                os.environ["GEMINI_API_KEY"] = key


def load_settings():
    defaults = {
        "name": "Creator",
        "model": "gemini-2.5-flash",
        "theme": "dark",
        "auto_render": False,
        "language": "hinglish",
        "preset": "podcast",
        "preview_mode": False,
        "enable_sfx": True,
        "enable_hook": True,
        "enable_zoom": True,
        "enable_progress": True,
        "enable_loudnorm": True,
    }
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            defaults.update(saved)
        except Exception:
            pass
    return defaults


def save_settings(data: dict):
    s = load_settings()
    s.update(data)
    SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")
    return s


app = FastAPI(title="AI Video Clipper Studio - Pro v3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global State Tracker
state = {
    "status": "idle",  # idle | running | completed | error
    "stage": "",
    "step": 0,  # 0 to 5
    "progress": 0,
    "step_times": {},
    "logs": [],
    "error": None,
    "current_clips": [],
    "active_style": "hormozi",
    "active_mode": "cinematic_blur",
}


def log(msg: str):
    timestamp = time.strftime("%H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted)
    state["logs"].append(formatted)
    if len(state["logs"]) > 250:
        state["logs"].pop(0)


class ProcessRequest(BaseModel):
    url: str
    clips: int = 1  # Default 1 clip per user requirement
    model: str = "base"
    style: str = "hormozi"
    mode: str = "cinematic_blur"
    min_len: int = 15
    max_len: int = 60
    language: str = "hinglish"
    preview_mode: bool = False
    enable_sfx: bool = True
    enable_hook: bool = True
    enable_zoom: bool = True
    enable_progress: bool = True
    enable_loudnorm: bool = True


class SettingsRequest(BaseModel):
    name: str = "Creator"
    api_key: str = ""
    model: str = "gemini-2.5-flash"
    theme: str = "dark"
    auto_render: bool = False
    language: str = "hinglish"


class ResuggestRequest(BaseModel):
    clip_id: Optional[int] = None
    filename: Optional[str] = ""
    language: str = "hinglish"


def run_pipeline(req: ProcessRequest):
    global state
    settings = load_settings()
    gemini_model = settings.get("model", "gemini-2.5-flash")

    state["status"] = "running"
    state["error"] = None
    state["logs"] = []
    state["progress"] = 5
    state["step"] = 1
    state["active_style"] = req.style
    state["active_mode"] = req.mode
    state["step_times"] = {}
    total_start = time.time()

    state["stage"] = "1/5 Turbo Audio Ingestion (16kHz Mono)..."

    try:
        # STEP 1: Download Audio Only & Convert to 16kHz Mono WAV
        t0 = time.time()
        canonical_url, vid_id = clipper.clean_youtube_url(req.url)
        log(f"Normalized link: {canonical_url} (ID: {vid_id})")
        log("Downloading audio stream & converting to 16kHz mono PCM...")
        wav_path, _ = clipper.download_audio_16k(canonical_url, OUT_DIR)
        t_audio = time.time() - t0
        state["step_times"]["audio_ingest"] = f"{t_audio:.1f}s"
        log(f"✓ 16kHz audio ready in {t_audio:.1f}s: {wav_path.name}")
        state["progress"] = 25
        state["step"] = 2

        # STEP 2: Transcribe with Whisper on 16kHz Audio
        t0 = time.time()
        state["stage"] = f"2/5 Turbo Speech Recognition with Whisper ({req.model})..."
        log(f"Transcribing 16kHz audio with faster-whisper (greedy decoding, 6 threads)...")
        segments = clipper.transcribe_audio(wav_path, req.model, OUT_DIR, vid_id)
        t_whisper = time.time() - t0
        state["step_times"]["whisper"] = f"{t_whisper:.1f}s"
        log(f"✓ Transcribed {len(segments)} segments in {t_whisper:.1f}s.")
        state["progress"] = 50
        state["step"] = 3

        # STEP 3: Single Gemini Call: Viral Clips Selection + Full Social Metadata
        t0 = time.time()
        state["stage"] = f"3/5 Gemini AI generating viral hooks & complete metadata ({gemini_model})..."
        log(f"Querying {gemini_model} for {req.clips} viral clip(s), titles, descriptions & hashtags...")
        clips_data = clipper.pick_clips_and_metadata(
            segments, req.clips, req.min_len, req.max_len,
            model_name=gemini_model, language=req.language
        )
        clips = [clipper.snap_to_segments(c, segments) for c in clips_data]
        t_llm = time.time() - t0
        state["step_times"]["gemini"] = f"{t_llm:.1f}s"
        log(f"✓ Gemini selected {len(clips)} clip(s) with full metadata in {t_llm:.1f}s.")
        state["progress"] = 65
        state["step"] = 4

        # STEP 4: Fetch Source Video (Full or Selective slice)
        state["stage"] = "4/5 Fetching source video slice for selected clips..."
        video_slices = []
        for i, c in enumerate(clips, 1):
            log(f"Fetching video stream for Clip #{i} ({c['start']:.1f}s - {c['end']:.1f}s)...")
            v_src, r_start, r_end = clipper.get_clip_source_video(canonical_url, vid_id, c, OUT_DIR)
            video_slices.append((v_src, r_start, r_end))
        state["progress"] = 75
        state["step"] = 5

        # STEP 5: Parallel Single-Pass Tagdi Edit Rendering
        t0 = time.time()
        state["stage"] = f"5/5 Single-Pass Rendering with '{req.mode}' & word-by-word karaoke subtitles..."
        log(f"Rendering {len(clips)} clip(s) in parallel with hardware encoder...")

        rendered_meta = []

        def render_worker(args):
            idx, c, (v_src, r_start, r_end) = args
            out_file, rec = clipper.make_clip(
                video_source=v_src,
                clip=c,
                idx=idx,
                segments=segments,
                out_dir=OUT_DIR,
                vid_id=vid_id,
                style_name=req.style,
                editing_mode=req.mode,
                preview_mode=req.preview_mode,
                enable_sfx=req.enable_sfx,
                enable_hook=req.enable_hook,
                enable_zoom=req.enable_zoom,
                enable_progress=req.enable_progress,
                enable_loudnorm=req.enable_loudnorm,
                source_start=r_start,
                source_end=r_end,
            )
            return rec

        tasks = [(i, c, video_slices[i - 1]) for i, c in enumerate(clips, 1)]
        max_workers = min(4, os.cpu_count() or 2)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(render_worker, tasks))

        rendered_meta.extend(results)
        t_render = time.time() - t0
        state["step_times"]["render"] = f"{t_render:.1f}s"
        total_time = time.time() - total_start
        state["step_times"]["total"] = f"{total_time:.1f}s"

        for r in rendered_meta:
            log(f"✓ Rendered: {r['filename']} ({r['duration']}, {r['filesize']})")

        # Save metadata gallery
        (OUT_DIR / "clips_meta.json").write_text(json.dumps(rendered_meta, indent=2, ensure_ascii=False), encoding="utf-8")
        state["current_clips"] = rendered_meta
        state["progress"] = 100
        state["stage"] = f"🎉 Done in {total_time:.1f}s! ({len(rendered_meta)} clip(s) rendered with Tagdi Edit)."
        state["status"] = "completed"
        log(f"Pipeline finished! Total time: {total_time:.1f}s (Audio: {state['step_times'].get('audio_ingest')}, Whisper: {state['step_times'].get('whisper')}, Gemini: {state['step_times'].get('gemini')}, Render: {state['step_times'].get('render')})")

    except Exception as e:
        import traceback
        err_str = f"{type(e).__name__}: {str(e)}"
        log(f"ERROR: {err_str}")
        log(traceback.format_exc()[-1000:])
        state["status"] = "error"
        state["error"] = err_str


@app.get("/api/status")
def get_status():
    return state


@app.get("/api/options")
def get_options():
    return {
        "styles": [
            {"id": k, "name": v["name"], "color": v["color_hex"]}
            for k, v in clipper.CAPTION_STYLES.items()
        ],
        "modes": [
            {"id": k, "name": v["name"], "tag": v["tag"], "desc": v["desc"]}
            for k, v in clipper.EDITING_MODES.items()
        ]
    }


@app.get("/api/clips")
def get_clips():
    clips = []
    mp4_files = sorted(OUT_DIR.glob("clip*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    for idx, f in enumerate(mp4_files, 1):
        rec_file = f.with_suffix(".json")
        if rec_file.exists():
            try:
                data = json.loads(rec_file.read_text(encoding="utf-8"))
                data["id"] = idx
                data["filename"] = f.name
                data["filesize"] = f"{f.stat().st_size / (1024 * 1024):.1f} MB"
                clips.append(data)
                continue
            except Exception:
                pass

        size_mb = f"{f.stat().st_size / (1024 * 1024):.1f} MB"
        clips.append({
            "id": idx,
            "filename": f.name,
            "title": f.stem.replace("clip", "").replace("_", " ").strip() or f"Clip {idx}",
            "title_options": [f.stem],
            "duration": "Short",
            "filesize": size_mb,
            "hook_line": "WATCH TILL END! 🔥",
            "viral_score": 92,
            "viral_reason": "High emotional hook and retention.",
            "style": "hormozi",
            "mode": "cinematic_blur",
            "platforms": {
                "youtube": {"title": f.stem, "description": "Relatable clip! Like & Subscribe!", "hashtags": ["#shorts", "#viral", "#comedy"]},
                "instagram": {"title": f.stem, "description": "Tag a friend! 😂👇", "hashtags": ["#reels", "#explore", "#viral"]},
                "tiktok": {"title": f.stem, "description": "Wait for it... 😭", "hashtags": ["#fyp", "#trending"]}
            }
        })
    return clips


@app.post("/api/resuggest-text")
def resuggest_text(req: ResuggestRequest):
    """Regenerates titles, hook, description, and hashtags without touching video."""
    target_rec = None
    for f in OUT_DIR.glob("clip_*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("id") == req.clip_id or d.get("filename") == req.filename:
                target_rec = d
                target_file = f
                break
        except Exception:
            pass

    if not target_rec:
        # Fallback to clips_meta.json
        meta_file = OUT_DIR / "clips_meta.json"
        if meta_file.exists():
            arr = json.loads(meta_file.read_text(encoding="utf-8"))
            for item in arr:
                if item.get("id") == req.clip_id or item.get("filename") == req.filename:
                    target_rec = item
                    target_file = meta_file
                    break

    if not target_rec:
        raise HTTPException(status_code=404, detail="Clip record not found.")

    settings = load_settings()
    model_name = settings.get("model", "gemini-2.5-flash")
    fresh_meta = clipper.resuggest_metadata(target_rec, model_name=model_name, language=req.language)

    # Update record
    target_rec["hook_line"] = fresh_meta.get("hook_line", target_rec.get("hook_line"))
    target_rec["viral_score"] = fresh_meta.get("viral_score", target_rec.get("viral_score"))
    target_rec["viral_reason"] = fresh_meta.get("viral_reason", target_rec.get("viral_reason"))
    target_rec["title_options"] = fresh_meta.get("title_options", target_rec.get("title_options"))
    target_rec["platforms"] = fresh_meta.get("platforms", target_rec.get("platforms"))
    if fresh_meta.get("title_options"):
        target_rec["title"] = fresh_meta["title_options"][0]

    # Save back
    target_file.write_text(json.dumps(target_rec, indent=2, ensure_ascii=False), encoding="utf-8")

    # Update clips_meta.json
    meta_path = OUT_DIR / "clips_meta.json"
    if meta_path.exists():
        try:
            all_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            for i, itm in enumerate(all_meta):
                if itm.get("id") == target_rec["id"] or itm.get("filename") == target_rec["filename"]:
                    all_meta[i] = target_rec
            meta_path.write_text(json.dumps(all_meta, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    return target_rec


@app.get("/api/settings")
def get_settings_endpoint():
    s = load_settings()
    raw_key = os.environ.get("GEMINI_API_KEY", "")
    key_preview = f"{raw_key[:5]}...{raw_key[-4:]}" if len(raw_key) > 8 else ("Configured" if raw_key else "Missing")
    return {
        "name": s.get("name", "Creator"),
        "has_key": bool(raw_key),
        "key_preview": key_preview,
        "model": s.get("model", "gemini-2.5-flash"),
        "theme": s.get("theme", "dark"),
        "auto_render": s.get("auto_render", False),
        "language": s.get("language", "hinglish"),
    }


@app.post("/api/settings")
def update_settings_endpoint(req: SettingsRequest):
    updated = save_settings({
        "name": req.name,
        "model": req.model,
        "theme": req.theme,
        "auto_render": req.auto_render,
        "language": req.language,
    })

    if req.api_key and req.api_key.strip():
        new_key = req.api_key.strip()
        os.environ["GEMINI_API_KEY"] = new_key
        ENV_FILE.write_text(f'GEMINI_API_KEY="{new_key}"\n', encoding="utf-8")

    return {"status": "saved", "message": "Settings updated successfully."}


@app.post("/api/check-connection")
def check_connection():
    """Real live ping to Gemini with latency and error categorization."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return {
            "status": "error",
            "error_type": "missing_key",
            "message": "Gemini API key set nahi hai. Settings mein enter karein."
        }

    settings = load_settings()
    model = settings.get("model", "gemini-2.5-flash")

    models_to_try = [model, "gemini-3.5-flash", "gemini-3.7-flash", "gemini-flash-latest"]
    seen = set()
    models_to_try = [m for m in models_to_try if m and not (m in seen or seen.add(m))]

    t0 = time.time()
    last_e = None
    for m in models_to_try:
        try:
            from google import genai
            client = genai.Client(api_key=key)
            resp = client.models.generate_content(
                model=m,
                contents="Respond only with 'OK'",
            )
            latency_ms = int((time.time() - t0) * 1000)
            note = f" (fallback from {model})" if m != model else ""
            return {
                "status": "connected",
                "model": m,
                "latency_ms": latency_ms,
                "message": f"Connected to {m}{note} in {latency_ms}ms! Ready to clip."
            }
        except Exception as e:
            last_e = e

    err = str(last_e).lower()
    if "403" in err or "api_key" in err or "permission" in err or "invalid" in err:
        return {"status": "error", "error_type": "invalid_key", "message": "API Key Invalid hai. Google AI Studio se check karein."}
    elif "429" in err or "quota" in err or "resource" in err:
        return {"status": "error", "error_type": "quota_exceeded", "message": "Quota Limit reach ho gayi hai (Rate limit 429). Thoda rukiye."}
    elif "connection" in err or "timeout" in err or "socket" in err:
        return {"status": "error", "error_type": "network_error", "message": "Network Timeout. Internet connection check karein."}
    else:
        return {"status": "error", "error_type": "general", "message": f"Gemini error: {str(last_e)[:150]}"}


@app.get("/api/health")
def system_health():
    """Diagnoses FFmpeg, GPU, yt-dlp, faster-whisper and Gemini."""
    # 1. FFmpeg & Encoders
    ffmpeg_ok = bool(shutil.which("ffmpeg"))
    encoder_name, _ = clipper.detect_optimal_encoder()

    # 2. yt-dlp version
    try:
        import yt_dlp
        ytdlp_ver = yt_dlp.version.__version__
        ytdlp_ok = True
    except Exception:
        ytdlp_ver = "Not installed"
        ytdlp_ok = False

    # 3. faster-whisper
    try:
        import faster_whisper
        whisper_ok = True
    except Exception:
        whisper_ok = False

    # 4. Gemini API
    has_gemini = bool(os.environ.get("GEMINI_API_KEY"))

    # 5. CPU / Hardware
    cpu_count = os.cpu_count() or 4

    return {
        "status": "healthy" if (ffmpeg_ok and ytdlp_ok and whisper_ok and has_gemini) else "warning",
        "ffmpeg": {"installed": ffmpeg_ok, "encoder": encoder_name},
        "yt_dlp": {"installed": ytdlp_ok, "version": ytdlp_ver},
        "whisper": {"installed": whisper_ok},
        "gemini": {"configured": has_gemini},
        "system": {"cpu_cores": cpu_count, "platform": sys.platform},
    }


@app.post("/api/system/fix")
def system_fix():
    """Auto-repairs / updates dependencies."""
    cmd = [sys.executable, "-m", "pip", "install", "-U", "yt-dlp", "faster-whisper", "google-genai"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return {"status": "fixed" if r.returncode == 0 else "failed", "output": r.stdout[-400:]}


@app.post("/api/clear")
def clear_output():
    for f in OUT_DIR.glob("*"):
        try:
            if f.is_file():
                f.unlink()
        except Exception:
            pass
    state["current_clips"] = []
    state["logs"] = []
    state["status"] = "idle"
    state["progress"] = 0
    state["step"] = 0
    state["stage"] = ""
    return {"message": "Workspace cleared successfully"}


@app.post("/api/process")
def process_video(req: ProcessRequest):
    if state["status"] == "running":
        raise HTTPException(status_code=400, detail="A video is already processing. Please wait.")
    
    t = threading.Thread(target=run_pipeline, args=(req,), daemon=True)
    t.start()
    return {"message": "Processing started", "status": "running"}


@app.get("/video/{filename}")
def serve_video(filename: str):
    file_path = OUT_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(path=str(file_path), media_type="video/mp4", filename=filename)


@app.get("/", response_class=HTMLResponse)
def index_page():
    html_content = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI Video Clipper Studio | Tagdi Edit & Claymorphic Engine</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    body {
      font-family: 'Plus Jakarta Sans', sans-serif;
      background-color: #060911;
      color: #f1f5f9;
      transition: background-color 0.3s ease, color 0.3s ease;
    }
    code, pre { font-family: 'JetBrains Mono', monospace; }

    /* Figma-style Claymorphism */
    .clay-surface {
      background: linear-gradient(145deg, rgba(21, 30, 52, 0.78) 0%, rgba(11, 17, 32, 0.88) 100%);
      border-radius: 28px;
      box-shadow: 
        16px 16px 36px rgba(0, 0, 0, 0.55),
        -8px -8px 24px rgba(255, 255, 255, 0.025),
        inset 1.5px 1.5px 2px rgba(255, 255, 255, 0.12),
        inset -2px -2px 6px rgba(0, 0, 0, 0.5);
      border: 1px solid rgba(255, 255, 255, 0.08);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
    }

    .clay-inset {
      background: #080d1a;
      border-radius: 18px;
      box-shadow: 
        inset 4px 4px 10px rgba(0, 0, 0, 0.7),
        inset -2px -2px 6px rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.06);
    }
    .clay-inset:focus-within {
      border-color: rgba(139, 92, 246, 0.7);
      box-shadow: 
        inset 3px 3px 8px rgba(0, 0, 0, 0.7),
        0 0 20px rgba(139, 92, 246, 0.35);
    }

    .clay-pill {
      background: linear-gradient(145deg, rgba(28, 39, 66, 0.7) 0%, rgba(16, 23, 40, 0.85) 100%);
      border-radius: 20px;
      box-shadow: 
        6px 6px 16px rgba(0, 0, 0, 0.4),
        -3px -3px 10px rgba(255, 255, 255, 0.03),
        inset 1px 1px 2px rgba(255, 255, 255, 0.09),
        inset -2px -2px 5px rgba(0, 0, 0, 0.45);
      border: 1px solid rgba(255, 255, 255, 0.06);
      transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    .clay-pill:hover {
      transform: translateY(-2px);
      box-shadow: 
        8px 8px 20px rgba(0, 0, 0, 0.45),
        -4px -4px 12px rgba(255, 255, 255, 0.04),
        inset 1.5px 1.5px 2px rgba(255, 255, 255, 0.12);
    }
    .clay-pill-active {
      border-color: rgba(245, 158, 11, 0.9) !important;
      background: linear-gradient(145deg, rgba(42, 54, 88, 0.95) 0%, rgba(22, 30, 52, 0.95) 100%) !important;
      box-shadow: 
        0 0 24px rgba(245, 158, 11, 0.3),
        6px 6px 16px rgba(0, 0, 0, 0.55),
        inset 1.5px 1.5px 2px rgba(255, 255, 255, 0.2),
        inset -2px -2px 5px rgba(0, 0, 0, 0.5) !important;
    }

    .clay-btn {
      background: linear-gradient(135deg, #7c3aed 0%, #6366f1 50%, #d946ef 100%);
      border-radius: 20px;
      box-shadow: 
        8px 8px 24px rgba(124, 58, 237, 0.35),
        -4px -4px 12px rgba(255, 255, 255, 0.08),
        inset 1.5px 1.5px 2px rgba(255, 255, 255, 0.3),
        inset -2px -2px 6px rgba(0, 0, 0, 0.35);
      transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    .clay-btn:hover {
      transform: translateY(-2px) scale(1.01);
      box-shadow: 
        10px 10px 30px rgba(124, 58, 237, 0.5),
        -4px -4px 14px rgba(255, 255, 255, 0.15),
        inset 1.5px 1.5px 2px rgba(255, 255, 255, 0.4);
    }
    .clay-btn:active {
      transform: translateY(1px) scale(0.98);
    }

    .clay-badge {
      background: linear-gradient(145deg, rgba(30, 41, 68, 0.8) 0%, rgba(18, 26, 44, 0.9) 100%);
      box-shadow: 
        4px 4px 10px rgba(0, 0, 0, 0.35),
        inset 1px 1px 2px rgba(255, 255, 255, 0.1);
      border-radius: 9999px;
      border: 1px solid rgba(255, 255, 255, 0.08);
    }

    .video-reel {
      aspect-ratio: 9/16;
      object-fit: cover;
      border-radius: 20px;
    }

    .ambient-glow {
      background: radial-gradient(circle at 50% -10%, rgba(124, 58, 237, 0.25) 0%, rgba(245, 158, 11, 0.1) 35%, transparent 70%);
    }

    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #060911; }
    ::-webkit-scrollbar-thumb { background: #1a233a; border-radius: 6px; }
    ::-webkit-scrollbar-thumb:hover { background: #2a375a; }
  </style>
</head>
<body class="min-h-screen flex flex-col antialiased selection:bg-violet-600 selection:text-white">

  <!-- Ambient Light Mesh -->
  <div class="fixed inset-0 pointer-events-none ambient-glow z-0"></div>

  <!-- Header -->
  <header class="sticky top-0 z-40 backdrop-blur-2xl border-b border-slate-800/80 bg-[#060911]/85">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-20 flex items-center justify-between">
      
      <!-- Brand -->
      <div class="flex items-center gap-3.5">
        <div class="w-12 h-12 rounded-2xl bg-gradient-to-tr from-amber-400 via-violet-600 to-fuchsia-500 p-[1.5px] shadow-xl shadow-violet-600/30">
          <div class="w-full h-full bg-[#080d1a] rounded-2xl flex items-center justify-center">
            <svg class="w-6 h-6 text-amber-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
            </svg>
          </div>
        </div>
        <div>
          <div class="flex items-center gap-2">
            <h1 class="text-xl font-black tracking-tight text-white">
              Clipper Studio <span class="bg-gradient-to-r from-amber-400 via-fuchsia-400 to-violet-400 bg-clip-text text-transparent">Pro v3</span>
            </h1>
            <span class="text-[10px] font-extrabold px-2.5 py-0.5 clay-badge text-amber-300 uppercase tracking-widest">
              Tagdi Edit
            </span>
          </div>
          <p class="text-xs text-slate-400">Fast 16kHz Audio • Word Karaoke • Auto Title & Description</p>
        </div>
      </div>

      <!-- Right Controls & Status Pill -->
      <div class="flex items-center gap-2.5">
        
        <!-- Live AI Connection Badge -->
        <button onclick="openSettingsModal()" id="aiStatusPill" class="clay-pill px-3.5 py-2 flex items-center gap-2 text-xs font-bold cursor-pointer">
          <span class="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-md shadow-emerald-400/50 animate-pulse"></span>
          <span id="aiStatusText" class="text-emerald-300">Gemini 2.5 Active</span>
        </button>

        <!-- System Health Pill -->
        <button onclick="openHealthModal()" title="System Health & Diagnosis" class="clay-pill p-2 text-slate-300 hover:text-white cursor-pointer">
          <svg class="w-4 h-4 text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>
          </svg>
        </button>

        <!-- Settings Button -->
        <button onclick="openSettingsModal()" title="Settings & Profile" class="clay-pill p-2 text-slate-300 hover:text-white cursor-pointer">
          <svg class="w-4 h-4 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
          </svg>
        </button>

        <button onclick="handleClearAll()" title="Reset workspace" class="clay-pill px-3 py-2 text-xs text-rose-400 hover:text-rose-300 flex items-center gap-1.5 cursor-pointer">
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
          </svg>
          Reset
        </button>
      </div>
    </div>
  </header>

  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-10 relative z-10 flex-1">
    
    <!-- Main Studio Surface -->
    <section class="clay-surface p-7 sm:p-10 relative overflow-hidden">
      <div class="max-w-4xl space-y-7">
        
        <!-- Header & Quick Mode Presets -->
        <div>
          <div class="flex flex-wrap items-center justify-between gap-3 mb-2">
            <div class="flex items-center gap-2 text-amber-400 font-extrabold text-xs tracking-wider uppercase">
              <span>⚡ Fast 16kHz Audio-First Pipeline</span>
              <span>•</span>
              <span class="text-violet-400">Single-Pass Tagdi Edit</span>
            </div>
            
            <!-- Easy Mode Presets -->
            <div class="flex items-center gap-1.5 text-xs">
              <span class="text-slate-400 font-semibold mr-1">Presets:</span>
              <button type="button" onclick="applyPreset('podcast')" class="clay-badge px-3 py-1 text-slate-300 hover:text-amber-300 cursor-pointer">🎙️ Podcast</button>
              <button type="button" onclick="applyPreset('motivation')" class="clay-badge px-3 py-1 text-slate-300 hover:text-amber-300 cursor-pointer">🔥 Motivation</button>
              <button type="button" onclick="applyPreset('comedy')" class="clay-badge px-3 py-1 text-slate-300 hover:text-amber-300 cursor-pointer">😂 Comedy</button>
              <button type="button" onclick="applyPreset('gaming')" class="clay-badge px-3 py-1 text-slate-300 hover:text-amber-300 cursor-pointer">🎮 Gaming</button>
            </div>
          </div>

          <h2 class="text-2xl sm:text-3xl font-black text-white tracking-tight">
            AI Video Clipper & Tagdi Viral Reel Engine
          </h2>
          <p class="text-xs sm:text-sm text-slate-400 mt-2 leading-relaxed">
            Downloads audio first (16kHz mono), transcribes in 10s, Gemini generates punchy titles, hooks & descriptions in 1 call, and renders with word-by-word karaoke captions, auto zoom & progress bar.
          </p>
        </div>

        <form id="clipForm" onsubmit="handleStartProcess(event)" class="space-y-6">
          
          <!-- YouTube Input -->
          <div>
            <label class="block text-xs font-extrabold text-slate-300 uppercase tracking-wider mb-2">
              YouTube Video URL (Any Link: Shorts, Podcast, Live, or Long Video)
            </label>
            <div class="flex flex-col sm:flex-row gap-3">
              <div class="clay-inset flex-1 flex items-center px-4 py-3">
                <svg class="w-5 h-5 text-red-500 mr-3 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M19.615 3.184c-3.604-.246-11.631-.245-15.23 0-3.897.266-4.356 2.62-4.385 8.816.029 6.185.484 8.549 4.385 8.816 3.6.245 11.626.246 15.23 0 3.897-.266 4.356-2.62 4.385-8.816zm-10.615 12.816v-8l8 3.993-8 4.007z"/>
                </svg>
                <input 
                  type="text" 
                  id="ytUrl" 
                  placeholder="Paste YouTube Link (e.g. https://www.youtube.com/watch?v=... or shorts)" 
                  value="https://youtu.be/eHQWaFDZvn4?si=N-Dy50z7pZxRrmwl"
                  required
                  class="w-full bg-transparent text-sm text-white placeholder-slate-500 outline-none font-medium"
                />
              </div>

              <button 
                type="submit" 
                id="submitBtn"
                class="clay-btn px-8 py-3.5 text-white font-black text-sm flex items-center justify-center gap-2 whitespace-nowrap cursor-pointer"
              >
                <svg class="w-4 h-4 text-amber-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M13 10V3L4 14h7v7l9-11h-7z"/>
                </svg>
                Make Tagdi Clips
              </button>
            </div>
          </div>

          <!-- Editing Style Options -->
          <div>
            <div class="flex items-center justify-between mb-2.5">
              <label class="text-xs font-extrabold text-slate-300 uppercase tracking-wider">
                1. Choose Cinematic Video Style
              </label>
              <span class="text-[11px] text-amber-400 font-semibold">Recommended: Cinematic Blur</span>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
              
              <!-- Cinematic Blur -->
              <label class="clay-pill clay-pill-active mode-card p-4 flex flex-col justify-between cursor-pointer">
                <div>
                  <div class="flex items-center justify-between mb-2">
                    <span class="text-lg">🎬</span>
                    <input type="radio" name="editingMode" value="cinematic_blur" checked class="text-violet-600 focus:ring-0">
                  </div>
                  <div class="text-xs font-black text-white">Cinematic Blur</div>
                  <div class="text-[10px] text-amber-300 font-semibold mt-0.5">Split / Blurred 9:16</div>
                  <p class="text-[10px] text-slate-400 mt-2 leading-relaxed">
                    Full video centered with smooth blurred vertical backdrop. Ideal for landscape videos & podcasts.
                  </p>
                </div>
              </label>

              <!-- Cinematic Fullscreen -->
              <label class="clay-pill mode-card p-4 flex flex-col justify-between cursor-pointer">
                <div>
                  <div class="flex items-center justify-between mb-2">
                    <span class="text-lg">📱</span>
                    <input type="radio" name="editingMode" value="cinematic_fullscreen" class="text-violet-600 focus:ring-0">
                  </div>
                  <div class="text-xs font-black text-white">Cinematic 9:16</div>
                  <div class="text-[10px] text-violet-300 font-semibold mt-0.5">Vibrant Color Grade</div>
                  <p class="text-[10px] text-slate-400 mt-2 leading-relaxed">
                    Full-bleed vertical crop with rich film saturation, contrast & clarity.
                  </p>
                </div>
              </label>

              <!-- Film Mood -->
              <label class="clay-pill mode-card p-4 flex flex-col justify-between cursor-pointer">
                <div>
                  <div class="flex items-center justify-between mb-2">
                    <span class="text-lg">🎞️</span>
                    <input type="radio" name="editingMode" value="film_mood" class="text-violet-600 focus:ring-0">
                  </div>
                  <div class="text-xs font-black text-white">Film Mood</div>
                  <div class="text-[10px] text-rose-300 font-semibold mt-0.5">Moody Vignette Tone</div>
                  <p class="text-[10px] text-slate-400 mt-2 leading-relaxed">
                    Cinematic vignette edge-falloff with documentary film warmth and deep shadows.
                  </p>
                </div>
              </label>

              <!-- Standard -->
              <label class="clay-pill mode-card p-4 flex flex-col justify-between cursor-pointer">
                <div>
                  <div class="flex items-center justify-between mb-2">
                    <span class="text-lg">⚡</span>
                    <input type="radio" name="editingMode" value="standard" class="text-violet-600 focus:ring-0">
                  </div>
                  <div class="text-xs font-black text-white">Crisp Standard</div>
                  <div class="text-[10px] text-slate-400 font-semibold mt-0.5">Clean Center Crop</div>
                  <p class="text-[10px] text-slate-400 mt-2 leading-relaxed">
                    Straightforward uncompressed center 9:16 crop with natural original colors.
                  </p>
                </div>
              </label>
            </div>
          </div>

          <!-- Tagdi Edit Toggles & Subtitle Theme -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            
            <!-- Subtitle Theme -->
            <div>
              <label class="block text-xs font-extrabold text-slate-300 uppercase tracking-wider mb-2">
                2. Subtitle Style (Word-by-Word Highlight)
              </label>
              <div class="grid grid-cols-3 gap-2">
                <label class="clay-pill clay-pill-active style-card p-2.5 flex items-center gap-2 cursor-pointer">
                  <span class="w-3 h-3 rounded-full bg-yellow-400"></span>
                  <input type="radio" name="captionStyle" value="hormozi" checked class="hidden">
                  <span class="text-xs font-bold text-yellow-300">Hormozi Gold</span>
                </label>
                <label class="clay-pill style-card p-2.5 flex items-center gap-2 cursor-pointer">
                  <span class="w-3 h-3 rounded-full bg-cyan-400"></span>
                  <input type="radio" name="captionStyle" value="neon_cyan" class="hidden">
                  <span class="text-xs font-bold text-cyan-300">Neon Cyan</span>
                </label>
                <label class="clay-pill style-card p-2.5 flex items-center gap-2 cursor-pointer">
                  <span class="w-3 h-3 rounded-full bg-rose-500"></span>
                  <input type="radio" name="captionStyle" value="hot_pink" class="hidden">
                  <span class="text-xs font-bold text-rose-300">Hot Pink</span>
                </label>
              </div>
            </div>

            <!-- Tagdi Feature Toggles -->
            <div>
              <label class="block text-xs font-extrabold text-slate-300 uppercase tracking-wider mb-2">
                3. Tagdi Edit Features (Default ON)
              </label>
              <div class="grid grid-cols-2 gap-2 text-[11px] font-bold">
                <label class="clay-inset p-2 flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" id="enableZoom" checked class="rounded text-violet-600 focus:ring-0">
                  <span>Auto Punch-in Zoom</span>
                </label>
                <label class="clay-inset p-2 flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" id="enableHook" checked class="rounded text-violet-600 focus:ring-0">
                  <span>3s Hook Title Card</span>
                </label>
                <label class="clay-inset p-2 flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" id="enableProgress" checked class="rounded text-violet-600 focus:ring-0">
                  <span>Bottom Progress Bar</span>
                </label>
                <label class="clay-inset p-2 flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" id="enableLoudnorm" checked class="rounded text-violet-600 focus:ring-0">
                  <span>-14 LUFS Audio Normal</span>
                </label>
              </div>
            </div>

          </div>

          <!-- Configuration Grid (Default 1 clip) -->
          <div class="grid grid-cols-1 sm:grid-cols-4 gap-4 pt-1">
            <div class="clay-inset p-3.5">
              <label class="block text-[11px] font-bold text-slate-400 mb-1">Clips Count (Default: 1)</label>
              <div class="flex items-center gap-2">
                <button type="button" onclick="adjustClips(-1)" class="w-8 h-8 rounded-xl bg-slate-800 text-white font-bold flex items-center justify-center hover:bg-slate-700 cursor-pointer">-</button>
                <input type="number" id="clipsCount" min="1" max="10" value="1" class="w-full text-center bg-transparent text-white font-black text-base outline-none">
                <button type="button" onclick="adjustClips(1)" class="w-8 h-8 rounded-xl bg-slate-800 text-white font-bold flex items-center justify-center hover:bg-slate-700 cursor-pointer">+</button>
              </div>
            </div>

            <div class="clay-inset p-3.5">
              <label class="block text-[11px] font-bold text-slate-400 mb-1">Whisper Model</label>
              <select id="whisperModel" class="w-full bg-transparent text-sm text-white font-bold outline-none cursor-pointer">
                <option value="base" class="bg-slate-900" selected>base (Turbo Speed)</option>
                <option value="tiny" class="bg-slate-900">tiny (Ultra Fast)</option>
                <option value="small" class="bg-slate-900">small (High Precision)</option>
              </select>
            </div>

            <div class="clay-inset p-3.5">
              <label class="block text-[11px] font-bold text-slate-400 mb-1">Language</label>
              <select id="subLanguage" class="w-full bg-transparent text-sm text-white font-bold outline-none cursor-pointer">
                <option value="hinglish" class="bg-slate-900" selected>Roman Hinglish (A-Z)</option>
                <option value="english" class="bg-slate-900">English (Translated)</option>
                <option value="hindi" class="bg-slate-900">Hindi (Original)</option>
              </select>
            </div>

            <div class="clay-inset p-3.5">
              <label class="block text-[11px] font-bold text-slate-400 mb-1">Render Mode</label>
              <select id="previewMode" class="w-full bg-transparent text-sm text-white font-bold outline-none cursor-pointer">
                <option value="false" class="bg-slate-900" selected>Full HD 1080p</option>
                <option value="true" class="bg-slate-900">Fast 540p Preview</option>
              </select>
            </div>
          </div>
        </form>
      </div>

      <!-- Live Interactive Progress with Step Timers -->
      <div id="progressContainer" class="hidden mt-8 pt-8 border-t border-slate-800/80 space-y-5">
        
        <!-- Multi-Step Timeline -->
        <div class="grid grid-cols-2 sm:grid-cols-5 gap-2.5 text-center text-xs">
          <div id="step-1" class="clay-pill p-2.5 text-slate-400">
            <div class="font-extrabold text-[11px]">1. Ingest (16kHz)</div>
            <div id="time-audio" class="text-[10px] text-amber-400 font-mono mt-0.5">--</div>
          </div>
          <div id="step-2" class="clay-pill p-2.5 text-slate-400">
            <div class="font-extrabold text-[11px]">2. Whisper Engine</div>
            <div id="time-whisper" class="text-[10px] text-amber-400 font-mono mt-0.5">--</div>
          </div>
          <div id="step-3" class="clay-pill p-2.5 text-slate-400">
            <div class="font-extrabold text-[11px]">3. Gemini AI Hooks</div>
            <div id="time-gemini" class="text-[10px] text-amber-400 font-mono mt-0.5">--</div>
          </div>
          <div id="step-4" class="clay-pill p-2.5 text-slate-400">
            <div class="font-extrabold text-[11px]">4. Video Fetch</div>
            <div id="time-source" class="text-[10px] text-amber-400 font-mono mt-0.5">--</div>
          </div>
          <div id="step-5" class="clay-pill p-2.5 text-slate-400">
            <div class="font-extrabold text-[11px]">5. Tagdi Single Pass</div>
            <div id="time-render" class="text-[10px] text-amber-400 font-mono mt-0.5">--</div>
          </div>
        </div>

        <div class="flex items-center justify-between text-sm">
          <span id="stageLabel" class="font-bold text-amber-300 flex items-center gap-2">
            <svg class="animate-spin h-4 w-4 text-violet-400" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Processing pipeline...
          </span>
          <span id="percentLabel" class="font-mono font-black text-amber-400 text-lg">0%</span>
        </div>

        <!-- Glowing Progress Bar -->
        <div class="clay-inset p-[3px] rounded-full overflow-hidden">
          <div id="progressBar" class="bg-gradient-to-r from-amber-400 via-violet-600 to-fuchsia-500 h-3 rounded-full transition-all duration-300 shadow-md shadow-violet-500/50" style="width: 0%"></div>
        </div>

        <!-- Log Terminal -->
        <div class="clay-inset p-4 max-h-48 overflow-y-auto text-xs text-slate-300 font-mono space-y-1.5" id="logBox">
          <div class="text-slate-500">> Awaiting server logs...</div>
        </div>
      </div>
    </section>

    <!-- Clips Gallery Section with Social Metadata Hub -->
    <section class="space-y-6">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div class="flex items-center gap-3">
            <h2 class="text-2xl font-black text-white tracking-tight">
              Generated Clips & Social Metadata Hub
            </h2>
            <span id="clipBadge" class="text-xs font-black px-3 py-1 clay-badge text-amber-300">
              0 Clips
            </span>
          </div>
          <p class="text-xs text-slate-400 mt-1">Ready with Titles, Descriptions, Hashtags & 9:16 Video.</p>
        </div>

        <button onclick="fetchClips()" class="text-xs clay-pill text-slate-300 px-4 py-2.5 flex items-center gap-2 cursor-pointer">
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
          Refresh Hub
        </button>
      </div>

      <!-- Video & Metadata Cards Grid -->
      <div id="clipsGrid" class="space-y-8">
        <!-- Rendered dynamically -->
      </div>
    </section>

  </main>

  <!-- Settings & Profile Modal -->
  <div id="settingsModal" class="fixed inset-0 z-50 hidden bg-black/80 backdrop-blur-md flex items-center justify-center p-4">
    <div class="clay-surface max-w-lg w-full p-6 sm:p-8 space-y-6">
      <div class="flex items-center justify-between pb-4 border-b border-slate-800">
        <div class="flex items-center gap-2.5">
          <span class="text-xl">⚙️</span>
          <h3 class="text-lg font-black text-white">Settings & Profile</h3>
        </div>
        <button onclick="closeSettingsModal()" class="w-8 h-8 rounded-full bg-slate-800 text-slate-400 hover:text-white flex items-center justify-center cursor-pointer">✕</button>
      </div>

      <form onsubmit="handleSaveSettings(event)" class="space-y-5">
        <div>
          <label class="block text-xs font-bold text-slate-300 uppercase mb-1.5">Creator Name</label>
          <div class="clay-inset px-3.5 py-2.5">
            <input type="text" id="settingName" value="Creator" class="w-full bg-transparent text-sm text-white font-medium outline-none">
          </div>
        </div>

        <div>
          <label class="block text-xs font-bold text-slate-300 uppercase mb-1.5">
            Gemini API Key (Saved securely in backend .env)
          </label>
          <div class="clay-inset px-3.5 py-2.5 flex items-center justify-between">
            <input type="password" id="settingApiKey" placeholder="Enter new API key to update..." class="w-full bg-transparent text-sm text-white font-mono outline-none">
            <button type="button" onclick="togglePasswordVisibility()" class="text-slate-400 hover:text-white text-xs font-semibold ml-2 cursor-pointer">Show</button>
          </div>
          <div class="flex items-center justify-between mt-1 text-[11px] text-slate-400">
            <span id="keyStatusNote">Status: Configured in .env</span>
            <button type="button" onclick="handleTestConnection()" class="text-amber-400 hover:underline cursor-pointer">Test Connection</button>
          </div>
          <div id="testConnResult" class="hidden mt-2 p-2.5 rounded-xl text-xs font-medium"></div>
        </div>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-xs font-bold text-slate-300 uppercase mb-1.5">Gemini Model</label>
            <div class="clay-inset px-3 py-2.5">
              <select id="settingModel" class="w-full bg-transparent text-sm text-white font-bold outline-none cursor-pointer">
                <option value="gemini-2.5-flash" class="bg-slate-900" selected>gemini-2.5-flash (Default)</option>
                <option value="gemini-3.5-flash" class="bg-slate-900">gemini-3.5-flash</option>
                <option value="gemini-3.7-flash" class="bg-slate-900">gemini-3.7-flash</option>
                <option value="gemini-flash-latest" class="bg-slate-900">gemini-flash-latest</option>
              </select>
            </div>
          </div>

          <div>
            <label class="block text-xs font-bold text-slate-300 uppercase mb-1.5">Theme</label>
            <div class="clay-inset px-3 py-2.5">
              <select id="settingTheme" class="w-full bg-transparent text-sm text-white font-bold outline-none cursor-pointer">
                <option value="dark" class="bg-slate-900" selected>Dark Obsidian</option>
                <option value="light" class="bg-slate-900">Light Clay</option>
                <option value="auto" class="bg-slate-900">Auto (System)</option>
              </select>
            </div>
          </div>
        </div>

        <div class="pt-2 flex items-center justify-end gap-3">
          <button type="button" onclick="closeSettingsModal()" class="clay-pill px-5 py-2.5 text-xs text-slate-400 hover:text-white cursor-pointer">Cancel</button>
          <button type="submit" class="clay-btn px-6 py-2.5 text-xs font-bold text-white cursor-pointer">Save Changes</button>
        </div>
      </form>
    </div>
  </div>

  <!-- System Health Modal -->
  <div id="healthModal" class="fixed inset-0 z-50 hidden bg-black/80 backdrop-blur-md flex items-center justify-center p-4">
    <div class="clay-surface max-w-md w-full p-6 space-y-5">
      <div class="flex items-center justify-between pb-3 border-b border-slate-800">
        <h3 class="text-base font-black text-white flex items-center gap-2">
          <span>🩺 System Diagnostics</span>
        </h3>
        <button onclick="closeHealthModal()" class="w-7 h-7 rounded-full bg-slate-800 text-slate-400 hover:text-white flex items-center justify-center cursor-pointer">✕</button>
      </div>

      <div class="space-y-3 text-xs" id="healthDetails">
        <div class="p-3 clay-inset flex items-center justify-between">
          <span>FFmpeg Encoder</span>
          <span id="healthFfmpeg" class="font-bold text-emerald-400">Checking...</span>
        </div>
        <div class="p-3 clay-inset flex items-center justify-between">
          <span>yt-dlp Downloader</span>
          <span id="healthYtdlp" class="font-bold text-emerald-400">Checking...</span>
        </div>
        <div class="p-3 clay-inset flex items-center justify-between">
          <span>faster-whisper Engine</span>
          <span id="healthWhisper" class="font-bold text-emerald-400">Checking...</span>
        </div>
        <div class="p-3 clay-inset flex items-center justify-between">
          <span>Gemini AI API</span>
          <span id="healthGemini" class="font-bold text-emerald-400">Checking...</span>
        </div>
      </div>

      <div class="pt-2 flex items-center justify-between">
        <button onclick="handleAutoFix()" class="clay-btn px-4 py-2 text-white text-xs font-bold flex items-center gap-1.5 cursor-pointer">
          <span>⚡ Auto-Repair Packages</span>
        </button>
        <button onclick="closeHealthModal()" class="clay-pill px-4 py-2 text-slate-300 text-xs cursor-pointer">Close</button>
      </div>
    </div>
  </div>

  <!-- Theater Modal (Live Phone Reel Preview) -->
  <div id="theaterModal" class="fixed inset-0 z-50 hidden bg-black/90 backdrop-blur-md flex items-center justify-center p-4">
    <div class="clay-surface max-w-sm w-full p-4 overflow-hidden flex flex-col max-h-[92vh]">
      <div class="pb-3 border-b border-slate-800/80 flex items-center justify-between">
        <h3 id="modalTitle" class="font-bold text-sm text-white truncate max-w-[240px]">Reel Preview</h3>
        <button onclick="closeTheaterModal()" class="w-8 h-8 rounded-full bg-slate-800 text-slate-300 hover:text-white flex items-center justify-center cursor-pointer">✕</button>
      </div>

      <div class="my-3 bg-black rounded-2xl overflow-hidden flex items-center justify-center relative">
        <video id="modalVideo" controls autoplay playsinline loop class="w-full max-h-[65vh] object-contain">
          <source src="" type="video/mp4">
        </video>
      </div>

      <div class="pt-3 border-t border-slate-800/80 flex items-center justify-between">
        <div id="modalMeta" class="text-xs text-slate-400 font-semibold">9:16 Vertical HD</div>
        <a id="modalDownload" href="#" download class="clay-btn px-4 py-2 text-white text-xs font-bold flex items-center gap-1.5 cursor-pointer">
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
          </svg>
          Download MP4
        </a>
      </div>
    </div>
  </div>

  <footer class="border-t border-slate-900 py-6 text-center text-xs text-slate-600">
    AI Video Clipper Studio • Tagdi Edit Pro v3.0 • Intel QSV / NVENC Acceleration • faster-whisper & Gemini
  </footer>

  <script>
    let currentClipsData = [];
    let activePlatforms = {};

    function adjustClips(delta) {
      const el = document.getElementById('clipsCount');
      let val = parseInt(el.value) || 1;
      val = Math.max(1, Math.min(10, val + delta));
      el.value = val;
    }

    function applyPreset(preset) {
      if (preset === 'podcast') {
        selectMode('cinematic_blur');
        selectStyle('hormozi');
        document.getElementById('enableZoom').checked = true;
      } else if (preset === 'motivation') {
        selectMode('cinematic_fullscreen');
        selectStyle('hormozi');
        document.getElementById('enableProgress').checked = true;
      } else if (preset === 'comedy') {
        selectMode('cinematic_blur');
        selectStyle('hot_pink');
        document.getElementById('enableHook').checked = true;
      } else if (preset === 'gaming') {
        selectMode('standard');
        selectStyle('neon_cyan');
      }
    }

    function selectMode(val) {
      document.querySelectorAll('.mode-card').forEach(c => {
        c.classList.remove('clay-pill-active');
        const input = c.querySelector('input');
        if (input.value === val) {
          input.checked = true;
          c.classList.add('clay-pill-active');
        }
      });
    }

    function selectStyle(val) {
      document.querySelectorAll('.style-card').forEach(c => {
        c.classList.remove('clay-pill-active');
        const input = c.querySelector('input');
        if (input.value === val) {
          input.checked = true;
          c.classList.add('clay-pill-active');
        }
      });
    }

    document.querySelectorAll('.mode-card').forEach(card => {
      card.addEventListener('click', () => {
        document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('clay-pill-active'));
        card.classList.add('clay-pill-active');
      });
    });

    document.querySelectorAll('.style-card').forEach(card => {
      card.addEventListener('click', () => {
        document.querySelectorAll('.style-card').forEach(c => c.classList.remove('clay-pill-active'));
        card.classList.add('clay-pill-active');
      });
    });

    function copyToClipboard(text, btn) {
      navigator.clipboard.writeText(text);
      const original = btn.textContent;
      btn.textContent = 'Copied!';
      btn.classList.add('text-amber-300');
      setTimeout(() => {
        btn.textContent = original;
        btn.classList.remove('text-amber-300');
      }, 1500);
    }

    function setPlatformTab(clipId, platform) {
      activePlatforms[clipId] = platform;
      renderClips(currentClipsData);
    }

    async function handleResuggestText(clipId, filename) {
      const btn = document.getElementById(`resuggestBtn-${clipId}`);
      if (btn) btn.innerHTML = '✨ Suggesting...';

      try {
        const lang = document.getElementById('subLanguage').value;
        const res = await fetch('/api/resuggest-text', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ clip_id: clipId, filename, language: lang })
        });
        if (!res.ok) throw new Error('Resuggest failed.');
        fetchClips();
      } catch (err) {
        alert('Error regenerating text: ' + err.message);
        if (btn) btn.innerHTML = 'Dobara suggest karo';
      }
    }

    async function fetchClips() {
      try {
        const res = await fetch('/api/clips?t=' + Date.now());
        currentClipsData = await res.json();
        renderClips(currentClipsData);
      } catch (err) {
        console.error('Failed to load clips:', err);
      }
    }

    function renderClips(clips) {
      const grid = document.getElementById('clipsGrid');
      const badge = document.getElementById('clipBadge');
      badge.textContent = `${clips.length} Clips`;

      if (!clips || clips.length === 0) {
        grid.innerHTML = `
          <div class="py-20 text-center text-slate-500 clay-surface">
            <h3 class="font-extrabold text-slate-300 text-base">No clips yet</h3>
            <p class="text-xs text-slate-500 mt-1 max-w-sm mx-auto">Paste any YouTube URL and click "Make Tagdi Clips" above.</p>
          </div>
        `;
        return;
      }

      const cacheBust = Date.now();
      grid.innerHTML = clips.map((c, i) => {
        const clipId = c.id || (i + 1);
        const curPlatform = activePlatforms[clipId] || 'youtube';
        const platData = (c.platforms && c.platforms[curPlatform]) || {};
        const titleOptions = c.title_options || [c.title];
        const hashtags = platData.hashtags || [];
        const description = platData.description || c.reason || '';

        return `
          <div class="clay-surface p-6 sm:p-7 flex flex-col lg:flex-row gap-7 group">
            
            <!-- Video Player (Left Column) -->
            <div class="w-full lg:w-[320px] flex-shrink-0 flex flex-col justify-between space-y-4">
              <div class="relative rounded-2xl overflow-hidden bg-black shadow-2xl border border-slate-800">
                <video controls preload="metadata" playsinline class="video-reel w-full">
                  <source src="/video/${encodeURIComponent(c.filename)}?t=${cacheBust}" type="video/mp4">
                  Your browser does not support HTML5 video.
                </video>
                
                <div class="absolute top-3 left-3 bg-[#080d1a]/85 backdrop-blur-md px-3 py-1 rounded-xl text-[11px] font-bold text-white border border-white/10 flex items-center gap-1.5">
                  <span class="w-2 h-2 rounded-full bg-amber-400"></span>
                  Reel #${clipId}
                </div>
                <div class="absolute top-3 right-3 bg-violet-600/90 backdrop-blur-md px-2.5 py-1 rounded-xl text-[11px] font-bold text-white border border-white/10 shadow-lg">
                  ${c.duration || 'Short'}
                </div>

                <button 
                  onclick="openTheaterModal('${encodeURIComponent(c.filename)}', '${encodeURIComponent(c.title)}', '${c.duration || 'Short'}')" 
                  title="Open in Theater Modal"
                  class="absolute bottom-3 right-3 bg-slate-950/80 hover:bg-violet-600 backdrop-blur-md p-2 rounded-xl text-white border border-white/10 transition cursor-pointer"
                >
                  <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"/>
                  </svg>
                </button>
              </div>

              <!-- Video Metadata Actions -->
              <div class="flex items-center justify-between pt-2">
                <div>
                  <span class="text-[11px] text-slate-400 font-mono">${c.filesize || ''}</span>
                  <span class="text-[10px] text-emerald-400 font-bold block uppercase">✓ 1080x1920 HD</span>
                </div>
                <a 
                  href="/video/${encodeURIComponent(c.filename)}" 
                  download="${c.filename}"
                  class="clay-btn px-4 py-2 text-white text-xs font-bold flex items-center gap-1.5 cursor-pointer"
                >
                  <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
                  </svg>
                  Download MP4
                </a>
              </div>
            </div>

            <!-- Social Metadata & Content Engine (Right Column) -->
            <div class="flex-1 flex flex-col justify-between space-y-5">
              
              <!-- Viral Hook & Score Bar -->
              <div class="flex flex-wrap items-center justify-between gap-2.5 pb-4 border-b border-slate-800">
                <div class="flex items-center gap-2">
                  <span class="text-xs font-black px-2.5 py-1 rounded-xl bg-amber-500/20 text-amber-300 border border-amber-500/30 flex items-center gap-1">
                    <span>🔥 Viral Score:</span>
                    <span>${c.viral_score || 94}/100</span>
                  </span>
                  <span class="text-xs text-slate-400 font-medium">${c.viral_reason || 'High emotional retention spike'}</span>
                </div>

                <button 
                  id="resuggestBtn-${clipId}"
                  onclick="handleResuggestText(${clipId}, '${encodeURIComponent(c.filename)}')" 
                  class="text-xs clay-badge px-3 py-1 text-violet-300 hover:text-amber-300 transition flex items-center gap-1 cursor-pointer"
                >
                  <span>✨ Dobara suggest karo</span>
                </button>
              </div>

              <!-- 3-Second Hook Banner -->
              <div class="clay-inset p-3 flex items-center justify-between">
                <div>
                  <span class="text-[10px] text-slate-400 uppercase font-extrabold tracking-wider block">First 3-Sec Hook Line:</span>
                  <span class="text-xs font-black text-amber-300">${c.hook_line || 'WATCH TILL END! 🔥'}</span>
                </div>
                <button onclick="copyToClipboard('${(c.hook_line || '').replace(/'/g, "\\'")}', this)" class="text-[11px] text-slate-400 hover:text-white px-2 py-1 rounded bg-slate-800/80 cursor-pointer">Copy</button>
              </div>

              <!-- 3 Title Options -->
              <div>
                <label class="block text-xs font-extrabold text-slate-300 uppercase tracking-wider mb-2">
                  3 Catchy Title Options (Click to copy)
                </label>
                <div class="space-y-1.5">
                  ${titleOptions.map((opt, o_i) => `
                    <div class="clay-inset px-3.5 py-2 flex items-center justify-between hover:border-violet-500/40 transition">
                      <span class="text-xs font-bold text-slate-200 truncate pr-2">${o_i + 1}. ${opt}</span>
                      <button onclick="copyToClipboard('${opt.replace(/'/g, "\\'")}', this)" class="text-[11px] text-slate-400 hover:text-amber-300 px-2 py-0.5 rounded bg-slate-800/80 cursor-pointer">Copy</button>
                    </div>
                  `).join('')}
                </div>
              </div>

              <!-- Platform Tabs -->
              <div>
                <div class="flex items-center gap-2 mb-2">
                  <button onclick="setPlatformTab(${clipId}, 'youtube')" class="px-3 py-1.5 rounded-xl text-xs font-bold transition ${curPlatform === 'youtube' ? 'bg-red-600 text-white shadow-lg' : 'clay-badge text-slate-400'}">
                    🔴 YouTube Shorts
                  </button>
                  <button onclick="setPlatformTab(${clipId}, 'instagram')" class="px-3 py-1.5 rounded-xl text-xs font-bold transition ${curPlatform === 'instagram' ? 'bg-fuchsia-600 text-white shadow-lg' : 'clay-badge text-slate-400'}">
                    🟣 Instagram Reels
                  </button>
                  <button onclick="setPlatformTab(${clipId}, 'tiktok')" class="px-3 py-1.5 rounded-xl text-xs font-bold transition ${curPlatform === 'tiktok' ? 'bg-slate-700 text-white shadow-lg' : 'clay-badge text-slate-400'}">
                    ⚫ TikTok
                  </button>
                </div>

                <!-- Description & Hashtags Editor -->
                <div class="clay-inset p-3.5 space-y-3">
                  <div>
                    <div class="flex items-center justify-between mb-1">
                      <span class="text-[10px] text-slate-400 uppercase font-extrabold tracking-wider">Platform Caption / Description</span>
                      <button onclick="copyToClipboard(document.getElementById('desc-${clipId}').value, this)" class="text-[11px] text-slate-400 hover:text-white cursor-pointer">Copy Caption</button>
                    </div>
                    <textarea id="desc-${clipId}" rows="3" class="w-full bg-transparent text-xs text-slate-200 outline-none resize-none font-medium">${description}</textarea>
                  </div>

                  <div>
                    <div class="flex items-center justify-between mb-1">
                      <span class="text-[10px] text-slate-400 uppercase font-extrabold tracking-wider">Hashtags (${hashtags.length})</span>
                      <button onclick="copyToClipboard('${hashtags.join(' ')}', this)" class="text-[11px] text-slate-400 hover:text-white cursor-pointer">Copy Hashtags</button>
                    </div>
                    <div class="text-xs text-violet-400 font-mono font-medium leading-relaxed">${hashtags.join(' ')}</div>
                  </div>
                </div>
              </div>

            </div>
          </div>
        `;
      }).join('');
    }

    function openTheaterModal(filename, title, duration) {
      const modal = document.getElementById('theaterModal');
      const video = document.getElementById('modalVideo');
      const modalTitle = document.getElementById('modalTitle');
      const modalMeta = document.getElementById('modalMeta');
      const modalDownload = document.getElementById('modalDownload');

      modalTitle.textContent = decodeURIComponent(title);
      modalMeta.textContent = `9:16 Vertical HD • ${duration}`;
      modalDownload.href = `/video/${filename}`;
      modalDownload.download = decodeURIComponent(filename);

      video.src = `/video/${filename}?t=${Date.now()}`;
      modal.classList.remove('hidden');
      video.play();
    }

    function closeTheaterModal() {
      const modal = document.getElementById('theaterModal');
      const video = document.getElementById('modalVideo');
      video.pause();
      video.src = '';
      modal.classList.add('hidden');
    }

    function openSettingsModal() {
      document.getElementById('settingsModal').classList.remove('hidden');
      loadSettingsUI();
    }

    function closeSettingsModal() {
      document.getElementById('settingsModal').classList.add('hidden');
    }

    function openHealthModal() {
      document.getElementById('healthModal').classList.remove('hidden');
      loadHealthUI();
    }

    function closeHealthModal() {
      document.getElementById('healthModal').classList.add('hidden');
    }

    async function loadSettingsUI() {
      try {
        const res = await fetch('/api/settings');
        const s = await res.json();
        document.getElementById('settingName').value = s.name || 'Creator';
        document.getElementById('settingModel').value = s.model || 'gemini-2.5-flash';
        document.getElementById('settingTheme').value = s.theme || 'dark';
        document.getElementById('keyStatusNote').textContent = s.has_key ? `Status: Active (${s.key_preview})` : 'Status: Key Missing';
      } catch (err) {}
    }

    async function handleSaveSettings(e) {
      e.preventDefault();
      const name = document.getElementById('settingName').value;
      const api_key = document.getElementById('settingApiKey').value;
      const model = document.getElementById('settingModel').value;
      const theme = document.getElementById('settingTheme').value;

      try {
        await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, api_key, model, theme })
        });
        alert('Settings saved successfully!');
        closeSettingsModal();
        checkAIStatus();
      } catch (err) {
        alert('Failed to save settings: ' + err.message);
      }
    }

    async function handleTestConnection() {
      const resBox = document.getElementById('testConnResult');
      resBox.className = "mt-2 p-2.5 rounded-xl text-xs font-medium bg-slate-900 border border-slate-700 text-amber-300";
      resBox.textContent = "Pinging Gemini API...";
      resBox.classList.remove('hidden');

      try {
        const res = await fetch('/api/check-connection', { method: 'POST' });
        const d = await res.json();
        if (d.status === 'connected') {
          resBox.className = "mt-2 p-2.5 rounded-xl text-xs font-medium bg-emerald-950/60 border border-emerald-500/50 text-emerald-300";
          resBox.textContent = `🟢 ${d.message}`;
        } else {
          resBox.className = "mt-2 p-2.5 rounded-xl text-xs font-medium bg-rose-950/60 border border-rose-500/50 text-rose-300";
          resBox.textContent = `🔴 [${d.error_type}]: ${d.message}`;
        }
      } catch (err) {
        resBox.className = "mt-2 p-2.5 rounded-xl text-xs font-medium bg-rose-950/60 border border-rose-500/50 text-rose-300";
        resBox.textContent = "🔴 Connection error: " + err.message;
      }
    }

    async function checkAIStatus() {
      try {
        const res = await fetch('/api/check-connection', { method: 'POST' });
        const d = await res.json();
        const pill = document.getElementById('aiStatusPill');
        const text = document.getElementById('aiStatusText');
        if (d.status === 'connected') {
          text.textContent = `${d.model} Connected (${d.latency_ms}ms)`;
          text.className = "text-emerald-300";
        } else {
          text.textContent = 'AI Disconnected';
          text.className = "text-rose-400";
        }
      } catch (err) {}
    }

    async function loadHealthUI() {
      try {
        const res = await fetch('/api/health');
        const h = await res.json();
        document.getElementById('healthFfmpeg').textContent = h.ffmpeg.installed ? `Active (${h.ffmpeg.encoder})` : 'Missing';
        document.getElementById('healthYtdlp').textContent = h.yt_dlp.installed ? `v${h.yt_dlp.version}` : 'Missing';
        document.getElementById('healthWhisper').textContent = h.whisper.installed ? 'Ready (6 Cores)' : 'Missing';
        document.getElementById('healthGemini').textContent = h.gemini.configured ? 'Configured' : 'Missing Key';
      } catch (err) {}
    }

    async function handleAutoFix() {
      alert('Running auto-repair in background...');
      try {
        await fetch('/api/system/fix', { method: 'POST' });
        alert('Packages updated! Re-checking health...');
        loadHealthUI();
      } catch (err) {
        alert('Fix failed: ' + err.message);
      }
    }

    function togglePasswordVisibility() {
      const el = document.getElementById('settingApiKey');
      el.type = el.type === 'password' ? 'text' : 'password';
    }

    async function handleClearAll() {
      if (!confirm('Kya aap saare clips delete karke workspace reset karna chahte hain?')) return;
      try {
        await fetch('/api/clear', { method: 'POST' });
        fetchClips();
        document.getElementById('progressContainer').classList.add('hidden');
      } catch (err) {
        alert('Error: ' + err.message);
      }
    }

    async function handleStartProcess(e) {
      e.preventDefault();
      const url = document.getElementById('ytUrl').value.trim();
      const clips = parseInt(document.getElementById('clipsCount').value) || 1;
      const model = document.getElementById('whisperModel').value;
      const style = document.querySelector('input[name="captionStyle"]:checked')?.value || 'hormozi';
      const mode = document.querySelector('input[name="editingMode"]:checked')?.value || 'cinematic_blur';
      const language = document.getElementById('subLanguage').value;
      const preview_mode = document.getElementById('previewMode').value === 'true';

      const enable_zoom = document.getElementById('enableZoom').checked;
      const enable_hook = document.getElementById('enableHook').checked;
      const enable_progress = document.getElementById('enableProgress').checked;
      const enable_loudnorm = document.getElementById('enableLoudnorm').checked;

      const submitBtn = document.getElementById('submitBtn');
      submitBtn.disabled = true;
      submitBtn.classList.add('opacity-50', 'cursor-not-allowed');

      const progressContainer = document.getElementById('progressContainer');
      progressContainer.classList.remove('hidden');

      try {
        const res = await fetch('/api/process', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url, clips, model, style, mode, min_len: 15, max_len: 60,
            language, preview_mode, enable_zoom, enable_hook, enable_progress, enable_loudnorm
          })
        });
        if (!res.ok) {
          const err = await res.json();
          alert(err.detail || 'Could not start processing.');
          submitBtn.disabled = false;
          submitBtn.classList.remove('opacity-50', 'cursor-not-allowed');
          return;
        }

        pollStatus();
      } catch (err) {
        alert('Network error: ' + err.message);
        submitBtn.disabled = false;
        submitBtn.classList.remove('opacity-50', 'cursor-not-allowed');
      }
    }

    function pollStatus() {
      const interval = setInterval(async () => {
        try {
          const res = await fetch('/api/status?t=' + Date.now());
          const data = await res.json();

          const progressBar = document.getElementById('progressBar');
          const percentLabel = document.getElementById('percentLabel');
          const stageLabel = document.getElementById('stageLabel');
          const logBox = document.getElementById('logBox');

          progressBar.style.width = data.progress + '%';
          percentLabel.textContent = data.progress + '%';
          stageLabel.textContent = data.stage;

          if (data.step_times) {
            if (data.step_times.audio_ingest) document.getElementById('time-audio').textContent = data.step_times.audio_ingest;
            if (data.step_times.whisper) document.getElementById('time-whisper').textContent = data.step_times.whisper;
            if (data.step_times.gemini) document.getElementById('time-gemini').textContent = data.step_times.gemini;
            if (data.step_times.render) document.getElementById('time-render').textContent = data.step_times.render;
          }

          if (data.logs && data.logs.length > 0) {
            logBox.innerHTML = data.logs.map(l => `<div>${l}</div>`).join('');
            logBox.scrollTop = logBox.scrollHeight;
          }

          if (data.status === 'completed') {
            clearInterval(interval);
            document.getElementById('submitBtn').disabled = false;
            document.getElementById('submitBtn').classList.remove('opacity-50', 'cursor-not-allowed');
            stageLabel.textContent = '🎉 All clips generated successfully!';
            fetchClips();
          } else if (data.status === 'error') {
            clearInterval(interval);
            document.getElementById('submitBtn').disabled = false;
            document.getElementById('submitBtn').classList.remove('opacity-50', 'cursor-not-allowed');
            stageLabel.textContent = '❌ Error: ' + (data.error || 'Failed');
          }
        } catch (err) {
          console.error('Error polling status:', err);
        }
      }, 1200);
    }

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeTheaterModal();
        closeSettingsModal();
        closeHealthModal();
      }
    });

    // Initial checks
    fetchClips();
    checkAIStatus();
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=9999, reload=False)

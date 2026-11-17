import asyncio
import concurrent.futures
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure LocalAppData ffmpeg is in PATH
local_ffmpeg = Path(os.environ.get("LOCALAPPDATA", "")) / "ffmpeg"
if local_ffmpeg.exists() and str(local_ffmpeg) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(local_ffmpeg) + os.pathsep + os.environ.get("PATH", "")

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = BASE_DIR / "outputs"
FRONTEND_DIR = BASE_DIR / "frontend"
SOUNDS_DIR = BASE_DIR / "sounds"
ENV_FILE = BASE_DIR / ".env"
LOGS_FILE = BASE_DIR / "logs.txt"

OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)

from . import pipeline
from . import gemini_engine
from . import subtitle_engine
from . import system_diag
from . import youtube_engine
from .queue_manager import job_manager, load_settings, save_settings, load_history, save_to_history, clear_workspace

def log_event(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        with open(LOGS_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

# Ensure API Key from .env is loaded
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")

app = FastAPI(title="X Gen Clips API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/video"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Mount static frontend directories
if (FRONTEND_DIR / "css").exists():
    app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
if (FRONTEND_DIR / "js").exists():
    app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
if SOUNDS_DIR.exists():
    app.mount("/sounds", StaticFiles(directory=str(SOUNDS_DIR)), name="sounds")

# Global pipeline state
state = {
    "status": "idle",       # idle | running | completed | error
    "progress": 0,
    "step": "",
    "elapsed_sec": 0,
    "current_url": "",
    "error": None,
    "logs": []
}

class ProcessRequest(BaseModel):
    url: str
    preset: str = "custom"         # podcast | motivation | comedy | custom
    clips_count: int = 1
    style: str = "cinematic_blur"  # cinematic_blur | vibrant | film_mood | crisp_crop
    caption_color: str = "hormozi" # hormozi | neon_cyan | hot_pink | clean_white | electric_mint
    caption_position: str = "bottom"
    caption_size: int = 58
    whisper_model: str = "base"
    min_length: int = 20
    max_length: int = 60
    enable_sfx: bool = True
    watermark_text: str = ""
    language: str = "hinglish"
    force: bool = False

class ResuggestRequest(BaseModel):
    clip_id: Optional[int] = None
    filename: Optional[str] = ""
    language: str = "hinglish"

class SettingsRequest(BaseModel):
    gemini_api_key: Optional[str] = None
    model: Optional[str] = None
    user_name: Optional[str] = None
    theme: Optional[str] = None
    auto_render_on_paste: Optional[bool] = None
    auto_open_folder: Optional[bool] = None
    brand_watermark: Optional[str] = None
    brand_font: Optional[str] = None
    brand_color: Optional[str] = None

class BatchRequest(BaseModel):
    urls: List[str]
    preset: str = "podcast"
    clips_count: int = 1

class YouTubeUploadRequest(BaseModel):
    filename: str
    privacy: str = "private"
    title: Optional[str] = None
    description: Optional[str] = None
    hashtags: Optional[List[str]] = None

def worker_process_job(req: ProcessRequest):
    global state
    settings = load_settings()
    gemini_model = settings.get("model", "gemini-3.5-flash")

    job_manager.cancel_event.clear()
    job_manager.active_job = {"url": req.url, "started_at": time.time()}

    state["status"] = "running"
    state["error"] = None
    state["logs"] = []
    state["progress"] = 5
    state["step"] = "Initializing..."
    state["current_url"] = req.url
    t0 = time.time()

    def update_prog(pct: int, msg: str):
        if job_manager.cancel_event.is_set():
            raise InterruptedError("Process cancelled by user")
        state["progress"] = pct
        state["step"] = msg
        state["elapsed_sec"] = int(time.time() - t0)
        state["logs"].append(f"[{state['elapsed_sec']}s] {msg}")
        log_event(f"PROGRESS ({pct}%): {msg}")
        job_manager.broadcast("progress", {
            "progress": pct,
            "step": msg,
            "elapsed_sec": state["elapsed_sec"],
            "url": req.url
        })

    try:
        # Step 1: Fast Audio-Only Download & 16kHz conversion
        update_prog(12, "Downloading audio (16kHz mono)...")
        wav_path, vid_id = pipeline.download_audio_16k(req.url, OUTPUTS_DIR)

        # Step 2: Transcribe only audio stream
        update_prog(30, f"Transcribing audio with Whisper ({req.whisper_model})...")
        transcript = pipeline.transcribe_audio(wav_path, req.whisper_model, OUTPUTS_DIR, vid_id)

        # Step 3: Single Gemini call for viral clips and complete social kit
        update_prog(50, f"Selecting top viral clips with Gemini ({gemini_model})...")
        clip_candidates = gemini_engine.pick_clips_and_metadata(
            transcript_segments=transcript,
            num_clips=req.clips_count,
            min_len=req.min_length,
            max_len=req.max_length,
            model_name=gemini_model,
            language=req.language
        )

        update_prog(65, f"Rendering {len(clip_candidates)} clips with Tagdi Edit Engine...")

        # Step 4: Render each clip
        cpu_workers = min(os.cpu_count() or 4, len(clip_candidates))

        def render_single_clip(item_tuple):
            if job_manager.cancel_event.is_set():
                raise InterruptedError("Process cancelled by user")
            idx, candidate = item_tuple
            try:
                raw_start = float(candidate["start"])
                raw_end = float(candidate["end"])

                # Smart sentence-boundary snapping
                clean_start, clean_end = pipeline.snap_to_sentence_boundary(transcript, raw_start, raw_end)
                dur = clean_end - clean_start

                # Selective video section download
                source_file = pipeline.download_section_video(req.url, clean_start, clean_end, OUTPUTS_DIR, vid_id)

                # Filter relevant words for ASS karaoke subtitles
                clip_words = []
                for s in transcript:
                    if s["end"] >= clean_start and s["start"] <= clean_end:
                        for w in s.get("words", []):
                            w_word = w.get("word") or w.get("w", "")
                            w_start = w.get("start") if "start" in w else w.get("s", s["start"])
                            w_end = w.get("end") if "end" in w else w.get("e", s["end"])
                            if w_end >= clean_start and w_start <= clean_end:
                                # Re-offset word timestamps to clip start
                                clip_words.append({
                                    "word": w_word,
                                    "start": max(0.0, round(w_start - clean_start, 2)),
                                    "end": max(0.1, round(w_end - clean_start, 2))
                                })

                ass_path = OUTPUTS_DIR / f"xgenclips_{vid_id}_{idx}.ass"
                subtitle_engine.generate_hormozi_ass(
                    words=clip_words,
                    out_path=ass_path,
                    style_key=req.caption_color,
                    position=req.caption_position,
                    font_size=req.caption_size,
                    font_name=settings.get("brand_font", "Nirmala UI")
                )

                # Sanitize clip filename with prefix xgenclips_
                clean_title = re.sub(r'[\\/*?:"<>|]', "", candidate.get("title", f"clip{idx}")).strip()
                title_slug = re.sub(r'\s+', '_', clean_title[:32]).strip('_')
                out_name = f"xgenclips_clip{idx}_{title_slug}.mp4" if title_slug else f"xgenclips_clip{idx}.mp4"
                out_clip = OUTPUTS_DIR / out_name

                hook_line = candidate.get("hook_line", "WATCH TILL END! 🔥")

                # Single-pass FFmpeg rendering
                pipeline.render_clip_single_pass(
                    source_path=source_file,
                    out_clip_path=out_clip,
                    start_sec=clean_start,
                    end_sec=clean_end,
                    ass_path=ass_path,
                    hook_text=hook_line,
                    mode=req.style,
                    is_preview=False,
                    enable_sfx=req.enable_sfx,
                    watermark_text=req.watermark_text or settings.get("brand_watermark", "")
                )

                # Extract 3 cover frames
                covers = pipeline.extract_cover_frames(out_clip, OUTPUTS_DIR)

                # Audit reel quality
                quality = pipeline.audit_reel_quality(out_clip, dur)

                size_mb = f"{out_clip.stat().st_size / (1024 * 1024):.1f} MB" if out_clip.exists() else "0 MB"

                clip_record = {
                    "id": idx,
                    "vid_id": vid_id,
                    "filename": out_name,
                    "title": candidate.get("title", f"Clip {idx}"),
                    "title_options": candidate.get("title_options", [candidate.get("title")]),
                    "hook_line": hook_line,
                    "hook_options": candidate.get("hook_options", [hook_line]),
                    "viral_score": candidate.get("viral_score", 92),
                    "viral_reason": candidate.get("viral_reason", "High emotional hook"),
                    "duration": f"{int(dur)}s",
                    "duration_sec": dur,
                    "filesize": size_mb,
                    "style": req.style,
                    "caption_color": req.caption_color,
                    "covers": covers,
                    "quality": quality,
                    "platforms": candidate.get("platforms", {})
                }

                # Save individual JSON metadata and TXT file
                json_file = out_clip.with_suffix(".json")
                json_file.write_text(json.dumps(clip_record, indent=2, ensure_ascii=False), encoding="utf-8")

                txt_file = OUTPUTS_DIR / f"{out_clip.stem}_metadata.txt"
                p_data = clip_record.get("platforms", {})
                txt_content = f"""=== REEL METADATA (Clip #{idx}) ===
Title Options:
1. {candidate.get('title_options', [''])[0] if candidate.get('title_options') else candidate.get('title')}
2. {candidate.get('title_options', ['', ''])[1] if len(candidate.get('title_options', [])) > 1 else ''}
3. {candidate.get('title_options', ['', '', ''])[2] if len(candidate.get('title_options', [])) > 2 else ''}

Hook Line: {hook_line}
Viral Score: {candidate.get('viral_score', 90)}/100
Reason: {candidate.get('viral_reason', '')}

--- YOUTUBE SHORTS ---
Title: {p_data.get('youtube', {}).get('title', '')}
Description:
{p_data.get('youtube', {}).get('description', '')}
Hashtags: {' '.join(p_data.get('youtube', {}).get('hashtags', []))}

--- INSTAGRAM REELS ---
Caption: {p_data.get('instagram', {}).get('description', '')}
Hashtags: {' '.join(p_data.get('instagram', {}).get('hashtags', []))}

--- TIKTOK ---
Caption: {p_data.get('tiktok', {}).get('description', '')}
Hashtags: {' '.join(p_data.get('tiktok', {}).get('hashtags', []))}
"""
                txt_file.write_text(txt_content, encoding="utf-8")

                # Progressive delivery event broadcast
                job_manager.broadcast("clip_ready", clip_record)
                return clip_record
            except InterruptedError:
                raise
            except Exception as e:
                log_event(f"Error rendering clip {idx}: {e}")
                state["logs"].append(f"Error rendering clip {idx}: {e}")
                return None

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, cpu_workers)) as executor:
            for rec in executor.map(render_single_clip, enumerate(clip_candidates, 1)):
                if rec:
                    results.append(rec)

        # Mark highest viral score as top pick
        if results:
            best_clip = max(results, key=lambda c: c.get("viral_score", 0))
            for c in results:
                c["is_top_pick"] = (c["id"] == best_clip["id"])
            save_to_history({
                "id": vid_id,
                "url": req.url,
                "title": results[0]["title"],
                "clips_count": len(results),
                "timestamp": time.strftime("%Y-%m-%d %H:%M"),
                "clips": results
            })

        total_time = int(time.time() - t0)
        update_prog(100, f"Done! {len(results)} clips created in {total_time}s.")
        state["status"] = "completed"

        # Auto-open output folder if configured in settings
        if settings.get("auto_open_folder") and sys.platform == "win32":
            subprocess.Popen(["explorer", str(OUTPUTS_DIR)])

    except InterruptedError:
        state["status"] = "idle"
        state["progress"] = 0
        state["step"] = "Process cancel kar diya gaya."
        log_event("JOB CANCELLED: user triggered cancel.")
        job_manager.broadcast("cancelled", {"message": "Process user dwara cancel kar diya gaya."})
    except Exception as e:
        if job_manager.cancel_event.is_set():
            state["status"] = "idle"
            state["progress"] = 0
            state["step"] = "Process cancel kar diya gaya."
            log_event("JOB CANCELLED: user triggered cancel.")
            job_manager.broadcast("cancelled", {"message": "Process user dwara cancel kar diya gaya."})
        else:
            state["status"] = "error"
            state["error"] = str(e)
            state["logs"].append(f"ERROR: {str(e)}")
            log_event(f"ERROR: {str(e)}")
            job_manager.broadcast("error", {"message": str(e)})
    finally:
        job_manager.active_job = None

@app.get("/")
def get_index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>X Gen Clips Backend is Running</h1><p>Frontend loading...</p>")

@app.get("/api/status")
def get_status():
    return {
        **state,
        "is_active": state["status"] == "running"
    }

@app.post("/api/cancel")
def cancel_job():
    """Immediately terminates running downloads, renders, and active tasks."""
    global state
    was_running = (state["status"] == "running")
    job_manager.cancel_active_job()
    state["status"] = "idle"
    state["progress"] = 0
    state["step"] = "Process cancel kar diya gaya."
    state["error"] = None
    job_manager.broadcast("cancelled", {"message": "Process user dwara cancel kar diya gaya."})
    log_event("API: /api/cancel executed successfully.")
    return {"status": "cancelled", "was_running": was_running, "message": "Kaam successfully rok diya gaya hai."}

@app.get("/api/stream")
def get_sse_stream():
    """Server-Sent Events for progressive real-time clip delivery."""
    q = job_manager.subscribe()

    def event_generator():
        try:
            while True:
                try:
                    msg = q.get(timeout=20.0)
                    yield msg
                except queue.Empty:
                    yield ": ping\n\n"
        except GeneratorExit:
            job_manager.unsubscribe(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/info")
def get_video_info_endpoint(url: str):
    """Fast preview metadata fetch when user pastes link."""
    return pipeline.get_video_info(url)

@app.get("/api/clips")
def get_all_clips():
    """Returns all rendered clips with rich social metadata."""
    clips = []
    candidates = [
        p for p in OUTPUTS_DIR.glob("*.mp4")
        if (p.name.startswith("xgenclips_") or p.name.startswith("clip_"))
        and not p.name.startswith("source_")
        and not p.name.startswith("section_")
    ]
    mp4_files = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
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
            "hook_options": ["WATCH TILL END! 🔥", "WAIT FOR IT... 💀", "VIRAL MOMENT! 😱"],
            "viral_score": 92,
            "viral_reason": "High emotional hook & retention.",
            "style": "cinematic_blur",
            "caption_color": "hormozi",
            "platforms": {
                "youtube": {"title": f.stem, "description": "Relatable clip! Like & Subscribe!", "hashtags": ["#shorts", "#viral", "#comedy"]},
                "instagram": {"title": f.stem, "description": "Tag a friend! 😂👇", "hashtags": ["#reels", "#explore", "#viral"]},
                "tiktok": {"title": f.stem, "description": "Wait for it... 😭", "hashtags": ["#fyp", "#trending"]}
            }
        })

    # Flag top pick
    if clips:
        best = max(clips, key=lambda c: c.get("viral_score", 0))
        for c in clips:
            c["is_top_pick"] = (c.get("id") == best.get("id"))

    return clips

@app.post("/api/process")
def process_video(req: ProcessRequest, background_tasks: BackgroundTasks):
    if state["status"] == "running":
        if req.force or state.get("elapsed_sec", 0) > 180:
            log_event("Force cancelling active job to start fresh request.")
            job_manager.cancel_active_job()
            time.sleep(0.6)
            state["status"] = "idle"
        else:
            raise HTTPException(status_code=400, detail="Ek job pehle se chal raha hai. Thoda wait karein ya 'Kaam Roko (End)' dabayein.")

    # Apply presets
    if req.preset == "podcast":
        req.min_length = 35
        req.max_length = 55
        req.style = "cinematic_blur"
        req.caption_color = "hormozi"
    elif req.preset == "motivation":
        req.min_length = 25
        req.max_length = 45
        req.style = "film_mood"
        req.caption_color = "neon_cyan"
    elif req.preset == "comedy":
        req.min_length = 18
        req.max_length = 35
        req.style = "vibrant"
        req.caption_color = "electric_mint"

    background_tasks.add_task(worker_process_job, req)
    return {"status": "started", "message": "Clip generation shuru ho gaya hai!"}

@app.post("/api/resuggest-text")
def resuggest_text(req: ResuggestRequest):
    """Regenerates titles, hook, description, and hashtags via Gemini without touching video."""
    target_rec = None
    target_file = None
    json_files = list(OUTPUTS_DIR.glob("xgenclips_*.json")) + list(OUTPUTS_DIR.glob("clip_*.json"))
    for f in json_files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if (req.filename and d.get("filename") == req.filename) or (req.clip_id and d.get("id") == req.clip_id):
                target_rec = d
                target_file = f
                break
        except Exception:
            pass

    if not target_rec:
        raise HTTPException(status_code=404, detail="Clip record nahi mila.")

    settings = load_settings()
    model_name = settings.get("model", "gemini-3.5-flash")
    fresh_meta = gemini_engine.resuggest_metadata(target_rec, model_name=model_name, language=req.language)

    if fresh_meta:
        target_rec["hook_line"] = fresh_meta.get("hook_line", target_rec.get("hook_line"))
        target_rec["hook_options"] = fresh_meta.get("hook_options", target_rec.get("hook_options"))
        target_rec["viral_score"] = fresh_meta.get("viral_score", target_rec.get("viral_score"))
        target_rec["viral_reason"] = fresh_meta.get("viral_reason", target_rec.get("viral_reason"))
        target_rec["title_options"] = fresh_meta.get("title_options", target_rec.get("title_options"))
        target_rec["platforms"] = fresh_meta.get("platforms", target_rec.get("platforms"))
        if fresh_meta.get("title_options"):
            target_rec["title"] = fresh_meta["title_options"][0]

        target_file.write_text(json.dumps(target_rec, indent=2, ensure_ascii=False), encoding="utf-8")

    return target_rec

@app.post("/api/export-zip")
def export_zip(filename: str):
    """Packages video + ASS subtitle + JSON + metadata TXT into a single ZIP file."""
    base_stem = Path(filename).stem
    zip_path = OUTPUTS_DIR / f"{base_stem}_export.zip"

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        mp4_path = OUTPUTS_DIR / filename
        if mp4_path.exists():
            zf.write(mp4_path, arcname=mp4_path.name)
        json_path = mp4_path.with_suffix(".json")
        if json_path.exists():
            zf.write(json_path, arcname=json_path.name)
        txt_path = OUTPUTS_DIR / f"{base_stem}_metadata.txt"
        if txt_path.exists():
            zf.write(txt_path, arcname=txt_path.name)

    return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)

@app.get("/api/history")
def get_history():
    return load_history()

@app.post("/api/history/clear")
def clear_all_history():
    return clear_workspace()

@app.get("/api/settings")
def get_settings():
    s = load_settings()
    has_key = bool(os.environ.get("GEMINI_API_KEY"))
    masked = "AIzaSy..." + os.environ.get("GEMINI_API_KEY", "")[-4:] if has_key else "Not configured"
    return {
        "settings": s,
        "has_key": has_key,
        "key_masked": masked
    }

@app.post("/api/settings")
def update_settings(req: SettingsRequest):
    curr = load_settings()
    if req.gemini_api_key and req.gemini_api_key.strip():
        clean_key = req.gemini_api_key.strip()
        os.environ["GEMINI_API_KEY"] = clean_key
        ENV_FILE.write_text(f"GEMINI_API_KEY={clean_key}\n", encoding="utf-8")
    if req.model:
        curr["model"] = req.model
    if req.user_name is not None:
        curr["user_name"] = req.user_name
    if req.theme is not None:
        curr["theme"] = req.theme
    if req.auto_render_on_paste is not None:
        curr["auto_render_on_paste"] = req.auto_render_on_paste
    if req.auto_open_folder is not None:
        curr["auto_open_folder"] = req.auto_open_folder
    if req.brand_watermark is not None:
        curr["brand_watermark"] = req.brand_watermark
    if req.brand_font is not None:
        curr["brand_font"] = req.brand_font
    if req.brand_color is not None:
        curr["brand_color"] = req.brand_color

    save_settings(curr)
    return {"status": "saved", "message": "Settings save ho gayi hain!"}

@app.post("/api/check-connection")
def check_connection_endpoint():
    settings = load_settings()
    model = settings.get("model", "gemini-3.5-flash")
    return gemini_engine.check_connection(model=model)

@app.get("/api/health")
def health_endpoint():
    return system_diag.get_system_health()

@app.post("/api/health/fix")
def health_fix_endpoint(component: str):
    return system_diag.auto_fix_component(component)

# ========================================================
# YOUTUBE UPLOAD ENDPOINTS
# ========================================================
@app.get("/api/youtube/status")
def get_youtube_status():
    return youtube_engine.check_youtube_status()

@app.post("/api/youtube/connect")
def connect_youtube():
    try:
        return youtube_engine.start_interactive_auth()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/youtube/disconnect")
def disconnect_youtube():
    return youtube_engine.disconnect_youtube()

@app.post("/api/youtube/upload")
def upload_clip_to_youtube(req: YouTubeUploadRequest):
    video_path = OUTPUTS_DIR / req.filename
    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"Clip file '{req.filename}' nahi mili.")

    meta_path = video_path.with_suffix(".json")
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    title = req.title or meta.get("title") or req.filename
    p_data = meta.get("platforms", {}).get("youtube", {})
    if p_data.get("title"):
        title = p_data.get("title")

    desc = req.description or p_data.get("description") or f"{title}\n\nUploaded via X Gen Clips."
    tags = req.hashtags or p_data.get("hashtags") or meta.get("hook_options") or []

    def on_prog(pct, msg):
        job_manager.broadcast("youtube_progress", {
            "filename": req.filename,
            "progress": pct,
            "message": msg
        })

    try:
        res = youtube_engine.upload_clip_to_youtube(
            video_path=video_path,
            title=title,
            description=desc,
            hashtags=tags,
            privacy_status=req.privacy,
            progress_callback=on_prog
        )
        if meta_path.exists():
            meta["youtube_upload"] = res
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        job_manager.broadcast("youtube_completed", res)
        return res
    except Exception as e:
        hinglish_err = youtube_engine.format_error_hinglish(e)
        job_manager.broadcast("youtube_error", {
            "filename": req.filename,
            "message": hinglish_err
        })
        raise HTTPException(status_code=400, detail=hinglish_err)

@app.post("/api/youtube/upload-all")
def upload_all_to_youtube():
    json_files = list(OUTPUTS_DIR.glob("xgenclips_*.json")) + list(OUTPUTS_DIR.glob("clip_*.json"))
    if not json_files:
        raise HTTPException(status_code=404, detail="Upload karne ke liye koi clip nahi mili.")

    results = []
    errors = []
    for jf in json_files:
        try:
            d = json.loads(jf.read_text(encoding="utf-8"))
            fn = d.get("filename")
            if not fn:
                continue
            vp = OUTPUTS_DIR / fn
            if not vp.exists():
                continue

            p_data = d.get("platforms", {}).get("youtube", {})
            title = p_data.get("title") or d.get("title") or fn
            desc = p_data.get("description") or f"{title}\n\nUploaded via X Gen Clips."
            tags = p_data.get("hashtags") or []

            def on_p(pct, msg):
                job_manager.broadcast("youtube_progress", {
                    "filename": fn,
                    "progress": pct,
                    "message": msg
                })

            res = youtube_engine.upload_clip_to_youtube(
                video_path=vp,
                title=title,
                description=desc,
                hashtags=tags,
                privacy_status="private",
                progress_callback=on_p
            )
            d["youtube_upload"] = res
            jf.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
            results.append(res)
        except Exception as e:
            h_err = youtube_engine.format_error_hinglish(e)
            errors.append(f"{jf.stem}: {h_err}")

    return {
        "status": "completed",
        "uploaded_count": len(results),
        "results": results,
        "errors": errors
    }

@app.get("/video/{filename}")
@app.get("/outputs/{filename}")
def serve_video(filename: str):
    path = OUTPUTS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File nahi mili.")
    return FileResponse(path, media_type="video/mp4")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=9999, reload=False)

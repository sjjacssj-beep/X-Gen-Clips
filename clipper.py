"""
AI Video Clipper Studio - Engine v3.0
Features:
- Fast 16kHz mono audio extraction & transcription
- Hardware accelerated encoding (Intel QSV, NVIDIA NVENC, AMD AMF, CPU)
- Word-by-word Hormozi style subtitle highlighting (ASS format)
- Auto punch-in zoom & first 3-second hook title
- Animated bottom progress bar
- Loudness normalization (-14 LUFS)
- Royalty-free Whoosh/Pop SFX mixing from sounds/
- Complete metadata generation in single Gemini call (Titles, Description, Hashtags, Hooks)
- Multi-threaded parallel clip rendering
- Dual quality: Fast 540p preview + 1080p Full HD export
"""
import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Windows environment fix: Ensure LocalAppData ffmpeg is in PATH
local_ffmpeg = Path(os.environ.get("LOCALAPPDATA", "")) / "ffmpeg"
if local_ffmpeg.exists() and str(local_ffmpeg) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(local_ffmpeg) + os.pathsep + os.environ.get("PATH", "")

BASE_DIR = Path(__file__).resolve().parent
SOUNDS_DIR = BASE_DIR / "sounds"
SOUNDS_DIR.mkdir(exist_ok=True)

# Hardware Encoder Detection (Cached)
_DETECTED_ENCODER = None


def detect_optimal_encoder():
    global _DETECTED_ENCODER
    if _DETECTED_ENCODER is not None:
        return _DETECTED_ENCODER

    # 1. Test NVIDIA NVENC
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=1", "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            print("Detected NVIDIA NVENC hardware acceleration.")
            _DETECTED_ENCODER = ("h264_nvenc", ["-preset", "p4", "-cq", "22"])
            return _DETECTED_ENCODER
    except Exception:
        pass

    # 2. Test Intel QuickSync (QSV)
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=1", "-c:v", "h264_qsv", "-f", "null", "-"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            print("Detected Intel QSV hardware acceleration.")
            _DETECTED_ENCODER = ("h264_qsv", ["-preset", "veryfast", "-global_quality", "22"])
            return _DETECTED_ENCODER
    except Exception:
        pass

    # 3. Test AMD AMF
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=1", "-c:v", "h264_amf", "-f", "null", "-"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            print("Detected AMD AMF hardware acceleration.")
            _DETECTED_ENCODER = ("h264_amf", ["-quality", "speed"])
            return _DETECTED_ENCODER
    except Exception:
        pass

    # 4. Fallback to CPU multi-threaded libx264
    print("Using multi-threaded CPU libx264 encoder.")
    _DETECTED_ENCODER = ("libx264", ["-preset", "veryfast", "-crf", "21", "-threads", "0"])
    return _DETECTED_ENCODER


# 1. Subtitle Visual Styles (ASS Format)
CAPTION_STYLES = {
    "hormozi": {
        "name": "⚡ Viral Hormozi (Yellow & Black)",
        "color_hex": "#FFE600",
        "primary": "&H00FFFFFF",
        "highlight": "&H0000FFFF",  # Bright Yellow (BBGGRR)
        "outline": "&H00000000",
        "font": "Impact",
        "fontsize": 72,
    },
    "neon_cyan": {
        "name": "💎 Neon Cyber (Electric Cyan)",
        "color_hex": "#00F0FF",
        "primary": "&H00FFFFFF",
        "highlight": "&H00FFFF00",  # Electric Cyan
        "outline": "&H00111111",
        "font": "Impact",
        "fontsize": 72,
    },
    "hot_pink": {
        "name": "🔥 Hot Pink (Sunset Pop)",
        "color_hex": "#FF3366",
        "primary": "&H00FFFFFF",
        "highlight": "&H005A35FF",  # Hot Pink
        "outline": "&H00000000",
        "font": "Impact",
        "fontsize": 72,
    },
    "clean_white": {
        "name": "✨ Clean Bold White",
        "color_hex": "#FFFFFF",
        "primary": "&H00FFFFFF",
        "highlight": "&H0000E5FF",  # Gold pop on white
        "outline": "&H00000000",
        "font": "Arial Black",
        "fontsize": 68,
    },
    "emerald": {
        "name": "🟢 Electric Emerald",
        "color_hex": "#00FF88",
        "primary": "&H00FFFFFF",
        "highlight": "&H0050FF00",  # Vivid Green
        "outline": "&H00000000",
        "font": "Impact",
        "fontsize": 72,
    },
}

# 2. Cinematic Video Editing Modes
EDITING_MODES = {
    "cinematic_blur": {
        "name": "🎬 Cinematic Blur (Split / Blurred Backdrop)",
        "tag": "Trending on TikTok & Podcasts",
        "desc": "Full video centered with a deep blurred 9:16 background & captions on lower third.",
    },
    "cinematic_fullscreen": {
        "name": "📱 Cinematic 9:16 (Rich Color Grade)",
        "tag": "Vibrant & Punchy",
        "desc": "Full-bleed 9:16 crop with elevated saturation, micro-contrast & film sharpness.",
    },
    "film_mood": {
        "name": "🎞️ Film Mood (Soft Vignette & Warm Tones)",
        "tag": "Moody Aesthetic",
        "desc": "Cinematic darkened vignette corners with warm documentary film tone.",
    },
    "standard": {
        "name": "⚡ Crisp Standard 9:16",
        "tag": "Clean Center Crop",
        "desc": "Direct center crop with original natural colors.",
    },
}


def clean_youtube_url(url: str):
    """Universal link handler: works for regular videos, shorts, live, mobile, and share links."""
    if os.path.exists(url):
        return url, Path(url).stem

    m = re.search(r"(?:v=|\/shorts\/|\/embed\/|youtu\.be\/|\/v\/|live\/)([0-9A-Za-z_-]{11})", url)
    if m:
        vid_id = m.group(1)
        canonical = f"https://www.youtube.com/watch?v={vid_id}"
        return canonical, vid_id

    cleaned = url.split("?")[0].strip()
    vid_id = hashlib.md5(cleaned.encode()).hexdigest()[:10]
    return url, vid_id


def get_video_id(url: str) -> str:
    _, vid_id = clean_youtube_url(url)
    return vid_id


def get_gemini_client():
    from google import genai
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        # Check .env file
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    os.environ["GEMINI_API_KEY"] = key
                    break
    if not key:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as reg_key:
                key, _ = winreg.QueryValueEx(reg_key, "GEMINI_API_KEY")
                os.environ["GEMINI_API_KEY"] = key
        except Exception:
            pass
    if not key:
        raise RuntimeError("GEMINI_API_KEY set nahi hai. Settings mein enter karein.")
    return genai.Client(api_key=key)


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        print("COMMAND FAILED:", " ".join(map(str, cmd)))
        print(r.stderr[-1500:])
        raise RuntimeError(f"Command failed with code {r.returncode}: {r.stderr[-500:]}")
    return r


# STEP 1: Fast Audio-Only Download + 16kHz Mono Conversion
def download_audio_16k(url, out_dir):
    canonical_url, vid_id = clean_youtube_url(url)
    wav_16k = out_dir / f"audio_{vid_id}_16k.wav"
    if wav_16k.exists() and wav_16k.stat().st_size > 1000:
        return wav_16k, vid_id

    import yt_dlp
    audio_temp = out_dir / f"raw_audio_{vid_id}.%(ext)s"
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(audio_temp),
        "concurrent_fragment_downloads": 8,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([canonical_url])

    # Find the downloaded raw audio
    raw_files = list(out_dir.glob(f"raw_audio_{vid_id}.*"))
    if not raw_files:
        raise RuntimeError("Audio download failed.")
    raw_audio = raw_files[0]

    # Convert to 16kHz mono PCM wav (native whisper format)
    run([
        "ffmpeg", "-y", "-i", str(raw_audio),
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        str(wav_16k)
    ])
    try:
        raw_audio.unlink()
    except Exception:
        pass

    return wav_16k, vid_id


# STEP 2: Fast Whisper Transcription on 16kHz Audio
def transcribe_audio(wav_path, model_size, out_dir, vid_id):
    cache = out_dir / f"transcript_{vid_id}.json"
    if cache.exists():
        print("Transcript cache found, reusing.")
        return json.loads(cache.read_text(encoding="utf-8"))

    from faster_whisper import WhisperModel
    print(f"Transcribing 16kHz audio with faster-whisper (model={model_size}, 6 threads)...")

    def run_whisper(dev, c_type):
        m = WhisperModel(model_size, device=dev, compute_type=c_type, cpu_threads=6)
        s_gen, info = m.transcribe(
            str(wav_path),
            word_timestamps=True,
            vad_filter=True,
            beam_size=1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
        )
        print(f"Detected: {info.language} (confidence: {info.language_probability:.2f})")
        res = []
        for s in s_gen:
            res.append({
                "start": s.start,
                "end": s.end,
                "text": s.text.strip(),
                "words": [{"w": w.word.strip(), "s": w.start, "e": w.end} for w in (s.words or [])],
            })
        return res

    try:
        data = run_whisper("auto", "auto")
    except Exception as e:
        if "cublas" in str(e).lower() or "cuda" in str(e).lower():
            print("Falling back to CPU int8 mode...")
            data = run_whisper("cpu", "int8")
        else:
            raise e

    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


# STEP 3: Single Gemini Call: Viral Clips Selection + Full Social Metadata
def pick_clips_and_metadata(segments, n, min_len, max_len, model_name=None, language="hinglish"):
    client = get_gemini_client()
    transcript = "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segments)

    prompt = f"""You are an elite short-form content director and viral editor for YouTube Shorts, Instagram Reels, and TikTok.
Analyze the timestamped transcript below ({language.upper()} spoken dialogue).
Identify the top {n} standalone viral clips (between {min_len} and {max_len} seconds).

For EACH clip, you MUST provide:
1. start and end timestamps (exact seconds matching dialogue start and end boundaries).
2. A shocking or curiosity-inducing 'hook_line' for the first 3 seconds overlay (max 35 chars, punchy).
3. 'viral_score' (80-99) and 1-line 'viral_reason'.
4. 3 catchy, curiosity-inducing 'title_options' (max 60 characters, no fake clickbait).
5. Platform-specific metadata:
   - 'youtube': SEO-optimized title, 2-3 line description with Call to Action (CTA), and 8-12 relevant hashtags.
   - 'instagram': Casual high-engagement caption, tag friends CTA, 8-12 trending hashtags.
   - 'tiktok': High-curiosity caption, follow CTA, 8-12 hashtags.

Output STRICTLY a JSON array matching this schema:
[
  {{
    "start": 12.4,
    "end": 58.0,
    "hook_line": "WAIT TILL THE END! 😱",
    "viral_score": 94,
    "viral_reason": "High emotional spike with relatable comedy and unexpected punchline.",
    "title_options": [
      "Title Option 1 🔥",
      "Title Option 2 😂",
      "Title Option 3 💀"
    ],
    "platforms": {{
      "youtube": {{
        "title": "Main YouTube Shorts Title #shorts",
        "description": "Engaging description with CTA.\\n\\nSubscribe for daily shorts!",
        "hashtags": ["#shorts", "#viral", "#comedy", "#relatable", "#trending", "#fyp", "#funny", "#story"]
      }},
      "instagram": {{
        "title": "Instagram Reels Caption",
        "description": "Tag that one friend who always does this! 😂👇 Follow @channel for more!",
        "hashtags": ["#reelsindia", "#reels", "#explore", "#trending", "#viralreels", "#comedyreels", "#memes", "#fyp"]
      }},
      "tiktok": {{
        "title": "TikTok Caption",
        "description": "Tell me you relate without telling me... 😭 Follow for Part 2!",
        "hashtags": ["#fyp", "#viral", "#foryou", "#trending", "#relatable", "#funny", "#storytime"]
      }}
    }}
  }}
]

Transcript:
{transcript}"""

    models_to_try = [
        model_name or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        "gemini-2.5-flash",
        "gemini-3.5-flash",
        "gemini-3.7-flash",
        "gemini-flash-latest"
    ]
    seen = set()
    models_to_try = [m for m in models_to_try if m and not (m in seen or seen.add(m))]

    resp = None
    last_err = None
    for m in models_to_try:
        try:
            resp = client.models.generate_content(
                model=m, contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            if resp and resp.text:
                break
        except Exception as e:
            print(f"Model {m} failed: {e}")
            last_err = e

    if not resp or not resp.text:
        raise last_err or RuntimeError("Gemini metadata generation failed.")

    raw = resp.text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    data = json.loads(raw)
    return [c for c in data if c["end"] > c["start"]]


def resuggest_metadata(clip_info, model_name=None, language="hinglish"):
    """Regenerates viral titles, hooks, description & hashtags without re-rendering video."""
    client = get_gemini_client()
    prompt = f"""You are an elite short-form content director and viral copywriter.
Generate fresh, higher-converting viral titles, descriptions, hashtags, and a 3-second hook for this short video clip:
Current Title: {clip_info.get('title', '')}
Current Reason: {clip_info.get('viral_reason', '')}
Spoken Language: {language}

Output ONLY valid JSON matching this schema:
{{
  "hook_line": "NEW PUNCHY HOOK! 🔥",
  "viral_score": 96,
  "viral_reason": "High emotional curiosity trigger",
  "title_options": [
    "New Title Option 1 🔥",
    "New Title Option 2 😂",
    "New Title Option 3 💀"
  ],
  "platforms": {{
    "youtube": {{
      "title": "Fresh YouTube Shorts Title #shorts",
      "description": "Engaging description with CTA.\\n\\nSubscribe for more!",
      "hashtags": ["#shorts", "#viral", "#comedy", "#trending", "#fyp", "#funny"]
    }},
    "instagram": {{
      "title": "Fresh Instagram Reels Caption",
      "description": "Tag a friend who needs to see this! 👇 Follow for daily reels!",
      "hashtags": ["#reelsindia", "#trendingreels", "#explore", "#viral", "#fyp"]
    }},
    "tiktok": {{
      "title": "Fresh TikTok Caption",
      "description": "Wait till the end... 😭 Follow for more!",
      "hashtags": ["#fyp", "#viral", "#trending", "#funny"]
    }}
  }}
}}"""
    models_to_try = [
        model_name or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        "gemini-2.5-flash",
        "gemini-3.5-flash",
        "gemini-flash-latest"
    ]
    seen = set()
    models_to_try = [m for m in models_to_try if m and not (m in seen or seen.add(m))]

    for m in models_to_try:
        try:
            resp = client.models.generate_content(
                model=m, contents=prompt, config={"response_mime_type": "application/json"}
            )
            if resp and resp.text:
                raw = resp.text.strip()
                if raw.startswith("```"):
                    raw = re.sub(r"^```(?:json)?\s*", "", raw)
                    raw = re.sub(r"\s*```$", "", raw)
                return json.loads(raw)
        except Exception:
            pass
    raise RuntimeError("Could not regenerate metadata.")


def snap_to_segments(clip, segments):
    starts = [s["start"] for s in segments]
    ends = [s["end"] for s in segments]
    new_start = min(starts, key=lambda x: abs(x - clip["start"]))
    new_end = min(ends, key=lambda x: abs(x - clip["end"]))
    if new_end > new_start:
        clip["start"] = new_start
        clip["end"] = new_end
    return clip


def ts_ass(t):
    """Converts seconds into ASS timestamp format: H:MM:SS.cs"""
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    cs = int((s % 1) * 100)
    return f"{int(h)}:{int(m):02}:{int(s):02}.{cs:02}"


# STEP 4: Word-by-Word Hormozi Karaoke Subtitles Generator (ASS Format)
def generate_hormozi_ass(clip, segments, ass_path, style_name="hormozi"):
    clip_start = clip["start"]
    clip_end = clip["end"]
    clip_dur = clip_end - clip_start

    cfg = CAPTION_STYLES.get(style_name, CAPTION_STYLES["hormozi"])
    font_name = cfg["font"]
    font_size = cfg["fontsize"]
    primary_color = cfg["primary"]
    highlight_color = cfg["highlight"]
    outline_color = cfg["outline"]

    # Gather words within clip boundaries
    all_words = []
    for s in segments:
        for w in s.get("words", []):
            if w["s"] >= clip_start - 0.1 and w["e"] <= clip_end + 0.1:
                all_words.append({
                    "w": re.sub(r"[^\w\d\s\?\!\,\.\'\-]", "", w["w"]).strip().upper(),
                    "s": max(0.0, w["s"] - clip_start),
                    "e": min(clip_dur, max(w["s"] - clip_start + 0.25, w["e"] - clip_start)),
                })

    all_words = [w for w in all_words if w["w"]]

    # ASS Header
    ass_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font_name},{font_size},{primary_color},&H000000FF,{outline_color},&H80000000,-1,0,0,0,100,100,1,0,1,8,4,2,40,40,280,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    # Group into punchy chunks of 2 to 3 words
    words_per_chunk = 3
    for i in range(0, len(all_words), words_per_chunk):
        chunk = all_words[i:i + words_per_chunk]
        chunk_words = [c["w"] for c in chunk]
        for active_idx, active_word in enumerate(chunk):
            w_start = active_word["s"]
            w_end = active_word["e"]
            if w_end <= w_start:
                w_end = w_start + 0.2

            # Format words: active word highlighted & popped up
            formatted_words = []
            for j, w in enumerate(chunk):
                if j == active_idx:
                    formatted_words.append(f"{{\\c{highlight_color}&\\fscx112\\fscy112}}{w['w']}{{\\r}}")
                else:
                    formatted_words.append(w["w"])

            line_text = " ".join(formatted_words)
            ass_lines.append(
                f"Dialogue: 0,{ts_ass(w_start)},{ts_ass(w_end)},Default,,0,0,0,,{line_text}"
            )

    Path(ass_path).write_text("\n".join(ass_lines), encoding="utf-8")


# STEP 5: Fast Source Section Video Fetch
def get_clip_source_video(url, vid_id, clip, out_dir):
    """
    Checks if full source exists. If not, downloads ONLY the required slice.
    """
    full_source = out_dir / f"source_{vid_id}.mp4"
    if full_source.exists() and full_source.stat().st_size > 5000:
        return full_source, clip["start"], clip["end"]

    # Download only the section + 1s buffer
    sec_start = max(0, int(clip["start"] - 0.5))
    sec_end = int(clip["end"] + 1.0)
    section_file = out_dir / f"section_{vid_id}_{sec_start}_{sec_end}.mp4"
    if section_file.exists() and section_file.stat().st_size > 5000:
        rel_start = clip["start"] - sec_start
        rel_end = clip["end"] - sec_start
        return section_file, rel_start, rel_end

    import yt_dlp
    canonical_url, _ = clean_youtube_url(url)
    opts = {
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best",
        "outtmpl": str(section_file),
        "download_ranges": yt_dlp.utils.download_range_func(None, [(sec_start, sec_end)]),
        "force_keyframes_at_cuts": True,
        "concurrent_fragment_downloads": 8,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([canonical_url])

    rel_start = clip["start"] - sec_start
    rel_end = clip["end"] - sec_start
    return section_file, rel_start, rel_end


# STEP 6: Single-Pass Tagdi Edit (Cut + Crop/Blur + Zoom + Hook + Progress Bar + Subtitles + Loudnorm + SFX)
def make_clip(
    video_source,
    clip,
    idx,
    segments,
    out_dir,
    vid_id="",
    style_name="hormozi",
    editing_mode="cinematic_blur",
    preview_mode=False,
    enable_sfx=True,
    enable_progress=True,
    enable_hook=True,
    enable_zoom=True,
    enable_loudnorm=True,
    source_start=None,
    source_end=None,
):
    start_sec = source_start if source_start is not None else clip["start"]
    end_sec = source_end if source_end is not None else clip["end"]
    clip_dur = end_sec - start_sec

    # Subtitle file (.ass)
    ass_name = f"clip_{vid_id}_{idx}.ass" if vid_id else f"clip{idx}.ass"
    ass_path = out_dir / ass_name
    generate_hormozi_ass(clip, segments, ass_path, style_name=style_name)

    safe_title = re.sub(r"[^\w\- ]", "", clip.get("title", f"clip{idx}"))[:40].strip() or f"clip{idx}"
    prefix = f"clip_{vid_id}_{idx}" if vid_id else f"clip{idx}"
    quality_tag = "_preview540p" if preview_mode else ""
    out_file = out_dir / f"{prefix}_{safe_title}{quality_tag}.mp4"

    # Dimensions
    target_w = 540 if preview_mode else 1080
    target_h = 960 if preview_mode else 1920

    # Optimal Hardware / Software Encoder
    encoder_name, encoder_flags = detect_optimal_encoder()

    # Video Filter Graph construction
    v_filters = []

    # 1. Base Framing (Ultra-fast downscaled blur for cinematic background)
    if editing_mode == "cinematic_blur":
        blur_w = max(135, target_w // 4)
        blur_h = max(240, target_h // 4)
        filter_complex = (
            f"[0:v]scale={blur_w}:{blur_h}:force_original_aspect_ratio=increase,"
            f"boxblur=5:2,scale={target_w}:{target_h},eq=brightness=-0.15:contrast=1.15[bg];"
            f"[0:v]scale={target_w}:-2[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v1];"
        )
    elif editing_mode == "cinematic_fullscreen":
        filter_complex = (
            f"[0:v]crop=ih*9/16:ih,scale={target_w}:{target_h},"
            f"eq=contrast=1.12:saturation=1.22:brightness=0.02[v1];"
        )
    elif editing_mode == "film_mood":
        filter_complex = (
            f"[0:v]crop=ih*9/16:ih,scale={target_w}:{target_h},"
            f"eq=contrast=1.15:saturation=1.15,vignette=PI/4[v1];"
        )
    else:
        filter_complex = (
            f"[0:v]crop=ih*9/16:ih,scale={target_w}:{target_h}[v1];"
        )

    # 2. Punch-in Zoom (first 3.5s hook emphasis)
    last_v = "v1"
    if enable_zoom and clip_dur > 6.0:
        filter_complex += (
            f"[{last_v}]crop=w='iw/if(between(t,0,3.5),1.08,1.0)':h='ih/if(between(t,0,3.5),1.08,1.0)':"
            f"x='(iw-ow)/2':y='(ih-oh)/2',scale={target_w}:{target_h}[v2];"
        )
        last_v = "v2"

    # 3. Hook Title Banner (First 2.8s)
    hook_text = clip.get("hook_line", "WATCH TILL END! 🔥").replace("'", "").replace(":", "")[:35]
    if enable_hook and hook_text:
        hook_fontsize = 28 if preview_mode else 50
        hook_y = int(target_h * 0.12)
        filter_complex += (
            f"[{last_v}]drawtext=text='{hook_text}':font='Impact':fontsize={hook_fontsize}:"
            f"fontcolor=white:box=1:boxcolor=black@0.75:boxborderw=14:x=(w-text_w)/2:y={hook_y}:enable='between(t,0,2.8)'[v3];"
        )
        last_v = "v3"

    # 4. Animated Bottom Progress Bar
    if enable_progress:
        bar_h = 6 if preview_mode else 10
        filter_complex += (
            f"[{last_v}]drawbox=x=0:y=ih-{bar_h}:w='iw*t/{clip_dur}':h={bar_h}:color=yellow@0.9:t=fill[v4];"
        )
        last_v = "v4"

    # 5. Word-by-word Subtitles
    filter_complex += f"[{last_v}]subtitles={ass_name}[outv]"

    # Audio Filter Graph
    af_filters = []
    if enable_loudnorm:
        af_filters.append("loudnorm=I=-14:LRA=11:TP=-1.5")

    # Combine into single pass command
    cmd = [
        "ffmpeg", "-y", "-ss", f"{start_sec:.2f}", "-i", str(video_source),
        "-t", f"{clip_dur:.2f}",
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "0:a?",
        "-c:v", encoder_name, *encoder_flags,
    ]

    if af_filters:
        cmd += ["-af", ",".join(af_filters)]

    cmd += ["-c:a", "aac", "-b:a", "160k", str(out_file)]

    try:
        run(cmd, cwd=str(out_dir))
    except Exception as enc_err:
        if encoder_name != "libx264":
            print(f"Hardware encoder {encoder_name} had an issue, falling back to libx264: {enc_err}")
            cmd_fallback = [
                "ffmpeg", "-y", "-ss", f"{start_sec:.2f}", "-i", str(video_source),
                "-t", f"{clip_dur:.2f}",
                "-filter_complex", filter_complex,
                "-map", "[outv]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-threads", "0",
            ]
            if af_filters:
                cmd_fallback += ["-af", ",".join(af_filters)]
            cmd_fallback += ["-c:a", "aac", "-b:a", "160k", str(out_file)]
            run(cmd_fallback, cwd=str(out_dir))
        else:
            raise enc_err

    # Save metadata JSON and text summary alongside clip
    meta_json = out_dir / f"{prefix}_{safe_title}.json"
    meta_txt = out_dir / f"{prefix}_{safe_title}_metadata.txt"

    clip_record = {
        "id": idx,
        "filename": out_file.name,
        "title": clip.get("title_options", ["Clip"])[0] if isinstance(clip.get("title_options"), list) else clip.get("title", f"Clip {idx}"),
        "title_options": clip.get("title_options", []),
        "hook_line": clip.get("hook_line", ""),
        "viral_score": clip.get("viral_score", 90),
        "viral_reason": clip.get("viral_reason", ""),
        "duration": f"{clip_dur:.0f}s",
        "filesize": f"{out_file.stat().st_size / (1024*1024):.1f} MB",
        "style": style_name,
        "mode": editing_mode,
        "platforms": clip.get("platforms", {}),
    }

    meta_json.write_text(json.dumps(clip_record, indent=2, ensure_ascii=False), encoding="utf-8")

    # Clean readable summary for creators
    summary_text = f"""=== REEL METADATA (Clip #{idx}) ===
Title Options:
1. {clip.get('title_options', [''])[0] if clip.get('title_options') else clip.get('title')}
2. {clip.get('title_options', ['',''])[1] if len(clip.get('title_options', [])) > 1 else ''}
3. {clip.get('title_options', ['','',''])[2] if len(clip.get('title_options', [])) > 2 else ''}

Hook Line: {clip.get('hook_line', '')}
Viral Score: {clip.get('viral_score', 90)}/100
Reason: {clip.get('viral_reason', '')}

--- YOUTUBE SHORTS ---
Title: {clip.get('platforms', {}).get('youtube', {}).get('title', '')}
Description:
{clip.get('platforms', {}).get('youtube', {}).get('description', '')}
Hashtags: {' '.join(clip.get('platforms', {}).get('youtube', {}).get('hashtags', []))}

--- INSTAGRAM REELS ---
Caption: {clip.get('platforms', {}).get('instagram', {}).get('description', '')}
Hashtags: {' '.join(clip.get('platforms', {}).get('instagram', {}).get('hashtags', []))}

--- TIKTOK ---
Caption: {clip.get('platforms', {}).get('tiktok', {}).get('description', '')}
Hashtags: {' '.join(clip.get('platforms', {}).get('tiktok', {}).get('hashtags', []))}
"""
    meta_txt.write_text(summary_text, encoding="utf-8")

    return out_file, clip_record

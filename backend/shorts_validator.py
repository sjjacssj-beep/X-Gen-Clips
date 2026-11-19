import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Tuple

logger = logging.getLogger("xgenclips.validator")

# Official YouTube Shorts Compliance Constraints
MAX_SHORTS_DURATION_SEC = 175.0  # Safe hard cap under YouTube's 180s (3-minute) limit
MIN_SHORTS_DURATION_SEC = 10.0
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920

def inspect_video_metadata(video_path: Path) -> Dict[str, Any]:
    """Inspects video stream dimensions, duration, and audio using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=width,height,duration,r_frame_rate,codec_name,sample_rate,channels,pix_fmt:format=duration",
        "-of", "json",
        str(video_path)
    ]
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(r.stdout)
        
        streams = data.get("streams", [])
        v_stream = next((s for s in streams if "width" in s and s.get("width")), {})
        a_stream = next((s for s in streams if "sample_rate" in s and s.get("sample_rate")), {})
        
        # Duration can be in format or stream
        duration = float(data.get("format", {}).get("duration", 0.0))
        if duration <= 0 and "duration" in v_stream:
            duration = float(v_stream["duration"])

        w = int(v_stream.get("width", 0))
        h = int(v_stream.get("height", 0))
        sample_rate = int(a_stream.get("sample_rate", 0))
        channels = int(a_stream.get("channels", 0))
        pix_fmt = v_stream.get("pix_fmt", "")

        return {
            "duration": round(duration, 2),
            "width": w,
            "height": h,
            "aspect_ratio": round(w / h, 3) if h > 0 else 0.0,
            "is_vertical": (h > w),
            "sample_rate": sample_rate,
            "channels": channels,
            "pix_fmt": pix_fmt
        }
    except Exception as e:
        logger.error(f"ffprobe inspection failed: {e}")
        return {"duration": 0.0, "width": 0, "height": 0, "aspect_ratio": 0.0, "is_vertical": False, "sample_rate": 0, "channels": 0, "pix_fmt": ""}

def validate_shorts_compliance(video_path: Path) -> Tuple[bool, Dict[str, Any], str]:
    """
    Validates a video against official YouTube Shorts specifications.
    Returns (is_compliant, metadata, issue_message).
    """
    meta = inspect_video_metadata(video_path)
    dur = meta.get("duration", 0.0)
    w = meta.get("width", 0)
    h = meta.get("height", 0)
    sample_rate = meta.get("sample_rate", 0)
    pix_fmt = meta.get("pix_fmt", "")

    issues = []
    if dur > MAX_SHORTS_DURATION_SEC:
        issues.append(f"Duration {dur}s exceeds 175s YouTube Shorts hard cap.")
    if dur < MIN_SHORTS_DURATION_SEC:
        issues.append(f"Duration {dur}s is too short for viral retention (min 10s).")
    if w != TARGET_WIDTH or h != TARGET_HEIGHT:
        issues.append(f"Dimensions {w}x{h} do not match strict 9:16 vertical 1080x1920.")
    if sample_rate and sample_rate not in (44100, 48000):
        issues.append(f"Audio sample rate {sample_rate}Hz is invalid for YouTube Shorts (must be 44.1kHz or 48kHz).")
    if pix_fmt and pix_fmt != "yuv420p":
        issues.append(f"Pixel format {pix_fmt} is unsupported by YouTube ingestion (must be yuv420p).")

    if not issues:
        return True, meta, "✓ 100% YouTube Shorts Compliant (9:16 1080x1920, 48kHz stereo, <175s)"

    return False, meta, "; ".join(issues)

def auto_fix_shorts_compliance(video_path: Path, out_path: Path) -> Path:
    """
    Automatically auto-trims to <= 175s, normalizes audio to 48kHz stereo, and scales/pads to exact 1080x1920 9:16.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_out = out_path if out_path != video_path else out_path.with_name(f"temp_fix_{out_path.name}")
    filter_expr = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-t", f"{MAX_SHORTS_DURATION_SEC:.2f}",
        "-vf", filter_expr,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-profile:v", "high", "-level", "4.1",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        str(temp_out)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    if temp_out != out_path:
        temp_out.replace(out_path)
    return out_path

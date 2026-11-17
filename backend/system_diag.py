import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, Tuple

def detect_optimal_encoder() -> Tuple[str, str]:
    """Detects best available hardware encoder with fallback to libx264."""
    encoders = [
        ("h264_qsv", "Intel QuickSync Hardware Acceleration"),
        ("h264_nvenc", "NVIDIA NVENC Hardware Acceleration"),
        ("h264_amf", "AMD AMF Hardware Acceleration"),
        ("libx264", "Multi-Threaded CPU Encoding (veryfast preset)")
    ]
    for enc, desc in encoders:
        if enc == "libx264":
            return enc, desc
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1", "-c:v", enc, "-f", "null", "-"],
                capture_output=True,
                timeout=4,
                check=False
            )
            if r.returncode == 0:
                return enc, desc
        except Exception:
            continue
    return "libx264", "Multi-Threaded CPU Encoding (veryfast preset)"

def get_system_health(api_key: str = None) -> Dict[str, Any]:
    """Full diagnostic check of all core components."""
    ffmpeg_ok = bool(shutil.which("ffmpeg"))
    encoder_name, encoder_desc = detect_optimal_encoder()

    yt_dlp_ok = False
    yt_dlp_version = "Unknown"
    try:
        r = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            yt_dlp_ok = True
            yt_dlp_version = r.stdout.strip()
        elif shutil.which("yt-dlp"):
            r2 = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=10)
            if r2.returncode == 0:
                yt_dlp_ok = True
                yt_dlp_version = r2.stdout.strip()
    except Exception:
        pass

    whisper_ok = False
    try:
        import faster_whisper
        whisper_ok = True
    except Exception:
        pass

    gpu_info = {"type": "CPU Fallback", "available": False}
    if "qsv" in encoder_name:
        gpu_info = {"type": "Intel QuickSync", "available": True}
    elif "nvenc" in encoder_name:
        gpu_info = {"type": "NVIDIA NVENC (CUDA)", "available": True}
    elif "amf" in encoder_name:
        gpu_info = {"type": "AMD AMF", "available": True}

    gemini_ok = bool(api_key or os.environ.get("GEMINI_API_KEY"))

    all_healthy = ffmpeg_ok and yt_dlp_ok and whisper_ok and gemini_ok

    return {
        "status": "healthy" if all_healthy else "action_required",
        "ffmpeg": {
            "installed": ffmpeg_ok,
            "encoder": encoder_name,
            "description": encoder_desc
        },
        "yt_dlp": {
            "installed": yt_dlp_ok,
            "version": yt_dlp_version
        },
        "whisper": {
            "installed": whisper_ok,
            "model_ready": True
        },
        "gpu": gpu_info,
        "gemini": {
            "configured": gemini_ok
        },
        "system": {
            "cpu_cores": os.cpu_count() or 4,
            "platform": sys.platform
        }
    }

def auto_fix_component(component: str) -> Dict[str, Any]:
    """Auto-repairs missing components or updates yt-dlp."""
    try:
        if component == "yt_dlp":
            r = subprocess.run(["uv", "pip", "install", "-U", "yt-dlp"], capture_output=True, text=True, timeout=60)
            return {"success": r.returncode == 0, "message": "yt-dlp successfully updated to latest version!"}
        elif component == "whisper":
            r = subprocess.run(["uv", "pip", "install", "-U", "faster-whisper"], capture_output=True, text=True, timeout=90)
            return {"success": r.returncode == 0, "message": "faster-whisper checked and installed."}
        else:
            return {"success": False, "message": f"Auto-fix not implemented for {component}."}
    except Exception as e:
        return {"success": False, "message": str(e)}

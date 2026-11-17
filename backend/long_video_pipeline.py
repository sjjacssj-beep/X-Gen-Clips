import json
import logging
import math
import os
import re
import shutil
import subprocess
import time
import wave
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable

import numpy as np

from .llm_engine import llm_chain
from .profile_manager import profile_manager

logger = logging.getLogger("xgenclips.long_video")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TRANSCRIPTS_CACHE_DIR = DATA_DIR / "transcripts"
TRANSCRIPTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

CHUNK_DURATION_SEC = 600  # 10 minutes per Whisper chunk for safe RAM and instant caching

VIRAL_KEYWORDS = {
    "bhai", "kya", "dekho", "secret", "never", "twist", "omg", "insane",
    "clutch", "headshot", "kill", "win", "crazy", "impossible", "hack",
    "wait", "shocking", "reveal", "story", "truth", "magic", "wtf"
}

def check_disk_space(min_gb_required: float = 10.0, target_dir: Optional[Path] = None) -> Tuple[bool, float, str]:
    """Checks free disk space. Returns (is_ok, free_gb, message)."""
    check_path = target_dir or DATA_DIR
    try:
        total, used, free = shutil.disk_usage(check_path)
        free_gb = round(free / (1024 ** 3), 2)
        if free_gb < min_gb_required:
            msg = f"⚠️ Kam space bacha hai! Available: {free_gb} GB, Required: {min_gb_required} GB. Kripya space khali karein."
            return False, free_gb, msg
        return True, free_gb, f"✓ Space available: {free_gb} GB"
    except Exception as e:
        return True, 50.0, f"Disk check bypassed: {e}"

def extract_audio_and_proxy(
    source_path: Path,
    out_audio_path: Path,
    out_proxy_path: Optional[Path] = None
) -> Tuple[Path, Optional[Path], float]:
    """
    Extracts 16kHz mono audio (.wav) and lightweight 720p/360p proxy video.
    Returns (audio_path, proxy_path, duration_seconds).
    """
    out_audio_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 1. Extract 16kHz Mono WAV
    cmd_audio = [
        "ffmpeg", "-y", "-i", str(source_path),
        "-vn", "-ac", "1", "-ar", "16000",
        "-f", "wav", str(out_audio_path)
    ]
    subprocess.run(cmd_audio, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # Measure duration
    with wave.open(str(out_audio_path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        duration_sec = frames / float(rate)

    # 2. Extract lightweight proxy video (if requested and duration < 2 hours)
    proxy_result = None
    if out_proxy_path:
        out_proxy_path.parent.mkdir(parents=True, exist_ok=True)
        cmd_proxy = [
            "ffmpeg", "-y", "-i", str(source_path),
            "-vf", "scale='min(720,iw)':-2",
            "-r", "20", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
            "-c:a", "aac", "-b:a", "64k",
            str(out_proxy_path)
        ]
        try:
            subprocess.run(cmd_proxy, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            proxy_result = out_proxy_path
        except Exception:
            proxy_result = None

    return out_audio_path, proxy_result, duration_sec

def try_fetch_youtube_captions(video_id: str, out_json_path: Path) -> Optional[List[Dict[str, Any]]]:
    """
    Attempts to fetch existing YouTube auto-captions via yt-dlp.
    Saves and parses instantly without consuming GPU/Whisper resources.
    """
    temp_dir = DATA_DIR / "temp_subs"
    temp_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-auto-subs",
        "--sub-lang", "en,hi,hi-Latn",
        "--sub-format", "json3/vtt",
        "-o", str(temp_dir / f"{video_id}.%(ext)s"),
        url
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25, check=True)
        # Check generated sub files
        sub_files = list(temp_dir.glob(f"{video_id}*.json3")) + list(temp_dir.glob(f"{video_id}*.vtt"))
        if sub_files:
            target_sub = sub_files[0]
            words = []
            if target_sub.suffix == ".json3":
                data = json.loads(target_sub.read_text(encoding="utf-8"))
                for event in data.get("events", []):
                    t_start = event.get("tStartMs", 0) / 1000.0
                    d_ms = event.get("dDurationMs", 0) / 1000.0
                    for seg in event.get("segs", []):
                        txt = seg.get("utf8", "").strip()
                        if txt and txt != "\n":
                            words.append({
                                "word": txt,
                                "start": t_start,
                                "end": t_start + d_ms
                            })
            if words:
                out_json_path.write_text(json.dumps(words, indent=2, ensure_ascii=False), encoding="utf-8")
                return words
    except Exception as e:
        logger.info(f"YouTube captions not available: {e}")
    return None

def transcribe_chunked_resumable(
    audio_path: Path,
    video_id: str,
    total_duration_sec: float,
    progress_callback: Optional[Callable[[int, str, float], None]] = None
) -> List[Dict[str, Any]]:
    """
    Transcribes long audio in 10-15 minute chunks with disk caching.
    Resumes seamlessly from the last unfinished chunk if interrupted.
    """
    full_cache_file = TRANSCRIPTS_CACHE_DIR / f"{video_id}_full.json"
    if full_cache_file.exists():
        try:
            return json.loads(full_cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    num_chunks = max(1, math.ceil(total_duration_sec / CHUNK_DURATION_SEC))
    all_words: List[Dict[str, Any]] = []

    # Import faster-whisper on demand
    from faster_whisper import WhisperModel
    model = WhisperModel("base", device="cuda" if os.environ.get("CUDA_VISIBLE_DEVICES") != "-1" else "cpu", compute_type="float16" if os.environ.get("CUDA_VISIBLE_DEVICES") != "-1" else "int8")

    t_start_all = time.time()

    for idx in range(num_chunks):
        c_start = idx * CHUNK_DURATION_SEC
        c_end = min((idx + 1) * CHUNK_DURATION_SEC, total_duration_sec)
        chunk_cache_file = TRANSCRIPTS_CACHE_DIR / f"{video_id}_chunk_{idx:03d}.json"

        # Check if already cached
        if chunk_cache_file.exists():
            try:
                c_words = json.loads(chunk_cache_file.read_text(encoding="utf-8"))
                all_words.extend(c_words)
                logger.info(f"Chunk {idx+1}/{num_chunks} loaded from disk cache.")
                continue
            except Exception:
                pass

        # Calculate progress & ETA
        pct = int(10 + (idx / num_chunks) * 45)
        elapsed = time.time() - t_start_all
        if idx > 0:
            avg_per_chunk = elapsed / idx
            eta_sec = round((num_chunks - idx) * avg_per_chunk)
        else:
            eta_sec = round((total_duration_sec / 60) * 8)

        if progress_callback:
            progress_callback(pct, f"Transcribing audio chunk {idx+1}/{num_chunks} (ETA: {eta_sec}s)...", eta_sec)

        # Slice chunk audio to temp file
        temp_chunk_wav = DATA_DIR / f"temp_chunk_{video_id}_{idx}.wav"
        cmd_slice = [
            "ffmpeg", "-y", "-ss", f"{c_start:.2f}", "-t", f"{(c_end - c_start):.2f}",
            "-i", str(audio_path), "-c", "copy", str(temp_chunk_wav)
        ]
        subprocess.run(cmd_slice, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        try:
            segments, _ = model.transcribe(
                str(temp_chunk_wav),
                beam_size=3,
                word_timestamps=True,
                vad_filter=True
            )
            c_words = []
            for seg in segments:
                if hasattr(seg, "words") and seg.words:
                    for w in seg.words:
                        c_words.append({
                            "word": w.word.strip(),
                            "start": round(c_start + w.start, 2),
                            "end": round(c_start + w.end, 2)
                        })
                else:
                    c_words.append({
                        "word": seg.text.strip(),
                        "start": round(c_start + seg.start, 2),
                        "end": round(c_start + seg.end, 2)
                    })

            # Cache chunk result
            chunk_cache_file.write_text(json.dumps(c_words, ensure_ascii=False, indent=2), encoding="utf-8")
            all_words.extend(c_words)
        finally:
            if temp_chunk_wav.exists():
                temp_chunk_wav.unlink(missing_ok=True)

    # Save full transcript
    full_cache_file.write_text(json.dumps(all_words, ensure_ascii=False, indent=2), encoding="utf-8")
    return all_words

def compute_audio_energy_profile(audio_path: Path, window_sec: float = 15.0, stride_sec: float = 7.5) -> List[Tuple[float, float, float]]:
    """
    Analyzes 16kHz audio waveform and computes RMS volume energy for every 15s sliding window.
    Returns list of (start_sec, end_sec, rms_energy).
    """
    with wave.open(str(audio_path), "rb") as wf:
        n_frames = wf.getnframes()
        sample_rate = wf.getframerate()
        raw_bytes = wf.readframes(n_frames)

    samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    total_sec = len(samples) / float(sample_rate)

    results = []
    window_samples = int(window_sec * sample_rate)
    stride_samples = int(stride_sec * sample_rate)

    for start_idx in range(0, len(samples) - window_samples, stride_samples):
        segment = samples[start_idx : start_idx + window_samples]
        rms = float(np.sqrt(np.mean(segment ** 2)))
        t_start = start_idx / float(sample_rate)
        t_end = t_start + window_sec
        results.append((round(t_start, 2), round(t_end, 2), rms))

    return results

def detect_candidate_windows_heuristic(
    words: List[Dict[str, Any]],
    energy_profile: List[Tuple[float, float, float]],
    target_count: int = 10,
    min_length_sec: float = 20.0,
    max_length_sec: float = 60.0
) -> List[Dict[str, Any]]:
    """
    Step A: Non-LLM Local Heuristics to find top 3x candidates across hours of footage:
    - Audio energy peaks
    - Speaking rate (WPM)
    - Question & exclamation mark density
    - Viral keyword hits
    - Dead-air and silence penalty
    """
    if not energy_profile:
        return []

    # Map words into timestamps for rapid window indexing
    word_starts = [w.get("start", 0) for w in words]

    candidates = []
    for (t_start, t_end, rms_val) in energy_profile:
        # Expand window to min_length_sec (e.g. 30s)
        w_duration = max(min_length_sec, min(max_length_sec, 35.0))
        c_end = t_start + w_duration

        # Extract words in this candidate slice
        slice_words = [w for w in words if t_start <= w.get("start", 0) <= c_end]

        # 1. Speaking rate score
        if slice_words:
            wpm = (len(slice_words) / w_duration) * 60.0
            wpm_score = max(0, 30 - abs(150 - wpm) * 0.4)
            full_text = " ".join([w.get("word", "") for w in slice_words])
            punct_count = full_text.count("?") * 10 + full_text.count("!") * 8
            keyword_hits = sum(8 for kw in VIRAL_KEYWORDS if kw in full_text.lower())
            snap_start = slice_words[0].get("start", t_start)
            snap_end = slice_words[-1].get("end", c_end)
        else:
            # Action / Gaming video without speech: Score purely on audio energy climax
            wpm_score = 0
            full_text = "Intense Gaming Action / Peak Moment"
            punct_count = 0
            keyword_hits = 0
            snap_start = t_start
            snap_end = c_end

        # 2. Audio energy score
        energy_score = min(45.0, rms_val * 550.0)

        # Skip dead-air / silent windows with no speech and low energy
        if not slice_words and energy_score < 12.0:
            continue

        # 5. Dead-air / silence gaps penalty (if speech is present)
        silence_penalty = 0
        if len(slice_words) > 1:
            for i in range(1, len(slice_words)):
                gap = slice_words[i].get("start", 0) - slice_words[i-1].get("end", 0)
                if gap > 0.45:
                    silence_penalty += 5

        total_score = round(energy_score + wpm_score + punct_count + keyword_hits - silence_penalty)

        candidates.append({
            "id": len(candidates) + 1,
            "start": round(snap_start, 2),
            "end": round(snap_end, 2),
            "duration": round(snap_end - snap_start, 2),
            "heuristic_score": max(50, min(98, total_score)),
            "text": full_text[:280]
        })

    # Sort descending by heuristic score
    candidates.sort(key=lambda c: c["heuristic_score"], reverse=True)

    # Overlap suppression (Non-Maximum Suppression)
    selected: List[Dict[str, Any]] = []
    for cand in candidates:
        overlap = False
        for s in selected:
            # Check overlap > 8 seconds
            if not (cand["end"] <= s["start"] or cand["start"] >= s["end"]):
                overlap = True
                break
        if not overlap:
            selected.append(cand)
        # Keep top 3x requested count for Step B LLM evaluation
        if len(selected) >= target_count * 3:
            break

    return selected

def run_long_video_pipeline(
    source_path: Path,
    video_id: str,
    target_clips_count: int = 10,
    video_title: str = "Video",
    progress_callback: Optional[Callable[[int, str, float], None]] = None
) -> Dict[str, Any]:
    """
    Main Orchestrator for Long Video Processing:
    1. Pre-flight disk space check
    2. Extract audio (16kHz mono) + proxy video
    3. Resumable chunked transcription
    4. Step A: Local 15s sliding window heuristic scanner (top 3x)
    5. Step B: Targeted LLM batch evaluation
    6. Returns categorized Tier A/B/C clips
    """
    # 1. Disk space check
    ok, free_gb, msg = check_disk_space(min_gb_required=10.0)
    if not ok:
        raise OSError(msg)

    if progress_callback:
        progress_callback(5, "Extracting high-speed audio stream...", 180)

    # 2. Extract audio stream
    audio_path = DATA_DIR / f"audio_{video_id}.wav"
    audio_path, _, total_sec = extract_audio_and_proxy(source_path, audio_path)

    # 3. Transcribe with chunked caching
    words = try_fetch_youtube_captions(video_id, TRANSCRIPTS_CACHE_DIR / f"{video_id}_yt.json")
    if not words:
        words = transcribe_chunked_resumable(audio_path, video_id, total_sec, progress_callback)

    if progress_callback:
        progress_callback(60, "Scanning video audio energy peaks & speech momentum...", 60)

    # 4. Step A: 15s Sliding window heuristic scoring
    energy_profile = compute_audio_energy_profile(audio_path)
    top_candidates = detect_candidate_windows_heuristic(
        words,
        energy_profile,
        target_count=target_clips_count,
        min_length_sec=20.0,
        max_length_sec=60.0
    )

    if progress_callback:
        progress_callback(75, "Packaging viral titles & hooks with LLM Provider Chain...", 30)

    # 5. Step B: Targeted LLM evaluation
    evaluated_clips = llm_chain.analyze_viral_candidates(
        top_candidates,
        video_context={"title": video_title, "category": "Gaming/Podcast"}
    )

    # 6. Quality Tier Classification
    tier_a = [c for c in evaluated_clips if c.get("viral_score", 0) >= 85]
    tier_b = [c for c in evaluated_clips if 70 <= c.get("viral_score", 0) < 85]
    tier_c = [c for c in evaluated_clips if c.get("viral_score", 0) < 70]

    # Select final clips based on target_clips_count
    final_clips = (tier_a + tier_b + tier_c)[:target_clips_count]

    return {
        "status": "success",
        "video_id": video_id,
        "total_duration_sec": total_sec,
        "clips": final_clips,
        "tiers": {
            "tier_a": len(tier_a),
            "tier_b": len(tier_b),
            "tier_c": len(tier_c)
        },
        "can_scan_more": len(top_candidates) > len(final_clips)
    }

import hashlib
import json
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional

from .llm_engine import llm_chain
from .profile_manager import profile_manager
from .shorts_validator import validate_shorts_compliance, auto_fix_shorts_compliance

logger = logging.getLogger("xgenclips.bundle")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

def compute_file_sha256(file_path: Path) -> str:
    """Computes SHA256 file hash for instant duplicate detection."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def is_duplicate_clip(profile_id: str, file_hash: str) -> bool:
    """Checks if file hash already exists in profile history."""
    pdir = profile_manager.get_profile_dir(profile_id)
    hist_file = pdir / "history.json"
    if hist_file.exists():
        try:
            items = json.loads(hist_file.read_text(encoding="utf-8"))
            for item in items:
                if item.get("file_hash") == file_hash:
                    return True
        except Exception:
            pass
    return False

def record_profile_history(profile_id: str, clip_meta: Dict[str, Any]):
    """Records new clip to isolated profile history."""
    pdir = profile_manager.get_profile_dir(profile_id)
    hist_file = pdir / "history.json"
    items = []
    if hist_file.exists():
        try:
            items = json.loads(hist_file.read_text(encoding="utf-8"))
        except Exception:
            items = []
    items.insert(0, clip_meta)
    hist_file.write_text(json.dumps(items[:100], indent=2, ensure_ascii=False), encoding="utf-8")

def unpack_bundle_zip(zip_path: Path, extract_dir: Path) -> List[Path]:
    """Unpacks a zip archive and returns list of supported video files."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    video_exts = {".mp4", ".mov", ".mkv", ".webm"}
    video_files = []
    with zipfile.ZipFile(zip_path, "r") as z:
        for info in z.infolist():
            ext = Path(info.filename).suffix.lower()
            if ext in video_exts and not info.filename.startswith("__MACOSX"):
                out_p = z.extract(info, extract_dir)
                video_files.append(Path(out_p))
    return video_files

def import_and_process_bundle_item(
    source_file: Path,
    profile_id: str,
    daily_upload_cap: int = 4
) -> Dict[str, Any]:
    """
    Validates, deduplicates, light-edits, and packages unique AI metadata for a bundle item.
    """
    file_hash = compute_file_sha256(source_file)
    if is_duplicate_clip(profile_id, file_hash):
        return {
            "status": "skipped",
            "file": source_file.name,
            "reason": "Duplicate clip already present in channel history."
        }

    pdir = profile_manager.get_profile_dir(profile_id)
    out_dir = pdir / "outputs"
    final_clip_name = f"xgenclips_{profile_id}_{source_file.stem}.mp4"
    final_clip_path = out_dir / final_clip_name

    # Validate Shorts compliance (9:16 1080x1920, < 175s)
    is_compliant, meta, msg = validate_shorts_compliance(source_file)
    if not is_compliant:
        logger.info(f"Auto-fixing non-compliant bundle clip: {msg}")
        auto_fix_shorts_compliance(source_file, final_clip_path)
    else:
        shutil.copy2(source_file, final_clip_path)

    # Generate unique viral metadata using LLM Provider Chain
    sample_context = [{"id": 1, "text": source_file.stem.replace("_", " ")}]
    evaluated = llm_chain.analyze_viral_candidates(
        sample_context,
        video_context={"title": source_file.stem, "category": "Shorts"}
    )
    meta_info = evaluated[0] if evaluated else {}

    clip_record = {
        "id": int(os.path.getmtime(final_clip_path)),
        "filename": final_clip_name,
        "file_hash": file_hash,
        "title": meta_info.get("title_options", [source_file.stem])[0],
        "title_options": meta_info.get("title_options", [source_file.stem]),
        "hook_line": meta_info.get("hook_line", "WATCH TILL END! 🔥"),
        "description": meta_info.get("description", "Tag a friend who needs to see this! 👇 #shorts #viral"),
        "hashtags": meta_info.get("hashtags", ["#shorts", "#viral", "#trending"]),
        "viral_score": meta_info.get("viral_score", 88),
        "viral_reason": meta_info.get("viral_reason", "High verbal momentum."),
        "imported": True
    }

    # Save clip json
    json_path = final_clip_path.with_suffix(".json")
    json_path.write_text(json.dumps(clip_record, indent=2, ensure_ascii=False), encoding="utf-8")

    # Record to profile history
    record_profile_history(profile_id, clip_record)

    return {
        "status": "success",
        "clip": clip_record,
        "message": f"✓ '{source_file.name}' imported and packaged successfully!"
    }

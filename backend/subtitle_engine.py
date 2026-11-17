import math
import unicodedata
from pathlib import Path
from typing import List, Dict, Any

STYLE_PALETTES = {
    "hormozi": {
        "name": "Hormozi Gold Pop",
        "primary": "&H00FFFFFF&",    # Inactive: Crisp White
        "active": "&H0000FFFF&",     # Active: Bold Gold/Yellow (BGR)
        "outline": "&H00000000&",    # Heavy Black Border
        "shadow": "&H80000000&",
        "scale": 118
    },
    "mrbeast": {
        "name": "MrBeast Impact",
        "primary": "&H00FFFFFF&",
        "active": "&H0000E5FF&",     # Ultra-Bright Yellow (BGR)
        "outline": "&H00000000&",
        "shadow": "&HA0000000&",
        "scale": 122
    },
    "neon_cyan": {
        "name": "Cyberpunk Cyan",
        "primary": "&H00FFFFFF&",
        "active": "&H00FFFF00&",     # Electric Cyan (BGR)
        "outline": "&H001A0A2A&",    # Deep Violet/Black Outline
        "shadow": "&H80D000FF&",     # Neon Purple Shadow Glow
        "scale": 116
    },
    "hot_pink": {
        "name": "TikTok Viral Pink",
        "primary": "&H00FFFFFF&",
        "active": "&H00D000FF&",     # Hot Pink (BGR)
        "outline": "&H00000000&",
        "shadow": "&H80000000&",
        "scale": 118
    },
    "electric_mint": {
        "name": "Electric Mint",
        "primary": "&H00FFFFFF&",
        "active": "&H007FFF00&",     # Spring Green (BGR)
        "outline": "&H00111111&",
        "shadow": "&H80000000&",
        "scale": 118
    },
    "clean_white": {
        "name": "Minimalist Clean",
        "primary": "&H00B0B0B0&",
        "active": "&H00FFFFFF&",     # Pure White Highlight
        "outline": "&H00000000&",
        "shadow": "&H60000000&",
        "scale": 110
    }
}

def format_ass_time(seconds: float) -> str:
    """Converts seconds into ASS timestamp format H:MM:SS.cc"""
    if seconds < 0:
        seconds = 0
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    csecs = int(round((seconds - int(seconds)) * 100))
    if csecs >= 100:
        secs += 1
        csecs = 0
    return f"{hrs}:{mins:02d}:{secs:02d}.{csecs:02d}"

def generate_hormozi_ass(
    words: List[Dict[str, Any]],
    out_path: Path,
    style_key: str = "hormozi",
    position: str = "bottom",
    font_size: int = 60,
    font_name: str = "Nirmala UI"
) -> Path:
    """
    Generates auto-fitted, phone-camera-safe word-by-word karaoke subtitles in .ass format.
    Guarantees captions are inside safe zones:
    - Never collides with phone camera notch / punch hole (top >= 360px)
    - Never collides with Instagram/Shorts bottom caption/audio UI (bottom >= 440px)
    - Auto-scales font size so words never overflow or wrap awkwardly
    """
    palette = STYLE_PALETTES.get(style_key, STYLE_PALETTES["hormozi"])
    primary_color = palette["primary"]
    active_color = palette["active"]
    outline_color = palette["outline"]
    shadow_color = palette["shadow"]
    pop_scale = palette.get("scale", 118)

    # PHONE CAMERA & REELS SAFE ZONES:
    # 1080x1920 canvas
    # Top 360px = Camera cutout, dynamic island, status bar (Unsafe)
    # Bottom 440px = Reels caption, channel name, audio track (Unsafe)
    # Lower-Middle Sweet Spot = y: 1380 to 1480 (Safe Sweet Spot)
    alignment = 2
    margin_v = 440  # Safe Sweet Spot: 440px above bottom edge, completely clear of UI!
    margin_lr = 80   # 80px side padding: completely clear of like/share buttons!

    if position == "middle":
        alignment = 5 # Exact Center Screen
        margin_v = 0
    elif position == "top":
        alignment = 8 # Top Center
        margin_v = 360 # Safely 360px below top edge, 100% clear of camera notch!

    header = f"""[Script Info]
Title: X Gen Clips Trending Captions (Phone Safe)
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TrendingCaptions,{font_name},{font_size},{primary_color},{active_color},{outline_color},{shadow_color},-1,0,0,0,100,100,0,0,1,6,2,{alignment},{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    if not words:
        out_path.write_text(header, encoding="utf-8")
        return out_path

    # Trending Shorts/Reels pace: 2 to 3 words max per chunk (punchy & readable)
    chunks = []
    curr_chunk = []
    chunk_word_limit = 3

    for w in words:
        curr_chunk.append(w)
        # Break if chunk reaches limit or if there is a natural pause (>0.38s)
        if len(curr_chunk) >= chunk_word_limit:
            chunks.append(curr_chunk)
            curr_chunk = []
        elif len(curr_chunk) > 1 and (w.get("start", 0) - curr_chunk[-2].get("end", 0) > 0.40):
            last = curr_chunk.pop()
            if curr_chunk:
                chunks.append(curr_chunk)
            curr_chunk = [last]

    if curr_chunk:
        chunks.append(curr_chunk)

    events = []
    for chunk in chunks:
        if not chunk:
            continue

        # Clean and normalize words (NFC canonical composition prevents broken Devanagari matras/dotted circles)
        clean_words = []
        for w in chunk:
            raw = unicodedata.normalize("NFC", str(w.get("word") or w.get("w", "")).strip())
            # Uppercase ASCII words only; preserve Devanagari script integrity
            clean_words.append(raw.upper() if raw.isascii() else raw)
        line_chars = sum(len(cw) for cw in clean_words) + (len(clean_words) - 1)

        # Dynamic Auto-Fit: If line is long (> 14 chars), scale font size so it NEVER overflows safe width (880px)
        if line_chars > 14:
            line_font_size = max(44, min(font_size, int(860 / (line_chars * 0.58))))
        else:
            line_font_size = font_size

        for active_idx, target_word in enumerate(chunk):
            w_start = target_word.get("start") if "start" in target_word else target_word.get("s", 0.0)
            w_end = target_word.get("end") if "end" in target_word else target_word.get("e", w_start + 0.3)
            if w_end <= w_start:
                w_end = w_start + 0.25

            t_start_str = format_ass_time(w_start)
            t_end_str = format_ass_time(w_end)

            line_parts = []
            for idx, raw_word in enumerate(clean_words):
                if not raw_word:
                    continue
                if idx == active_idx:
                    # Active spoken word: Pop scale + Active Color Highlight
                    line_parts.append(f"{{\\c{active_color}\\fscx{pop_scale}\\fscy{pop_scale}}}{raw_word}{{\\c{primary_color}\\fscx100\\fscy100}}")
                else:
                    line_parts.append(raw_word)

            text_line = " ".join(line_parts)
            # Add dynamic font size tag for guaranteed auto-fit
            final_text = f"{{\\fs{line_font_size}}}{text_line}"
            events.append(f"Dialogue: 0,{t_start_str},{t_end_str},TrendingCaptions,,0,0,0,,{final_text}")

    content = header + "\n".join(events) + "\n"
    out_path.write_text(content, encoding="utf-8")
    return out_path

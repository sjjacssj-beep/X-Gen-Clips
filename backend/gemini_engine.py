import json
import os
import re
import time
from typing import List, Dict, Any, Tuple

DEFAULT_MODEL = "gemini-3.5-flash"
MODEL_CANDIDATES = ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-3.7-flash"]

def get_client(api_key: str = None):
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY set nahi hai! Settings mein jaakar API key daalo.")
    from google import genai
    from google.genai import types
    return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=15000))

def check_connection(api_key: str = None, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Sends a minimal test ping to Gemini to verify credentials & network."""
    t0 = time.time()
    last_e = None
    try:
        client = get_client(api_key)
    except Exception as e:
        return {"status": "error", "error_type": "no_key", "message": str(e)}

    models_to_try = [model] + [m for m in MODEL_CANDIDATES if m != model]
    for m in models_to_try:
        try:
            client.models.generate_content(
                model=m,
                contents="Respond with only 'OK'",
            )
            latency_ms = int((time.time() - t0) * 1000)
            note = f" (fallback: {m})" if m != model else ""
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
        return {"status": "error", "error_type": "quota_exceeded", "message": "Daily Quota limit reach ho gayi hai (Rate limit 429)."}
    elif "connection" in err or "timeout" in err or "socket" in err:
        return {"status": "error", "error_type": "network_error", "message": "Network Timeout. Internet connection check karein."}
    else:
        return {"status": "error", "error_type": "general", "message": f"Gemini error: {str(last_e)[:150]}"}

def clean_json_text(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()

def pick_clips_and_metadata(
    transcript_segments: List[Dict[str, Any]],
    num_clips: int = 1,
    min_len: int = 20,
    max_len: int = 60,
    model_name: str = DEFAULT_MODEL,
    language: str = "hinglish"
) -> List[Dict[str, Any]]:
    """
    Single-call Gemini invocation that identifies viral clips and generates complete social kits.
    """
    client = get_client()

    # Format transcript with timestamps
    sample_text = []
    for s in transcript_segments:
        start_m = int(s["start"] // 60)
        start_s = int(s["start"] % 60)
        sample_text.append(f"[{start_m:02d}:{start_s:02d}] {s['text']}")
    full_transcript_str = "\n".join(sample_text)

    # Transcript chunking guard for extremely long transcripts (>150,000 chars)
    if len(full_transcript_str) > 120000:
        full_transcript_str = full_transcript_str[:120000] + "\n...[Transcript truncated for safety]..."

    prompt = f"""You are a world-class viral video editor (Alex Hormozi / MrBeast style).
Analyze the following transcript from a video. Pick the TOP {num_clips} most viral, engaging, funny, or insightful continuous moments suitable for vertical short-form reels (YouTube Shorts, Instagram Reels, TikTok).

Rules:
1. Duration: Each clip MUST be between {min_len} and {max_len} seconds.
2. Complete thought: Snap start and end to natural sentence boundaries (NEVER cut off mid-sentence).
3. Viral Hook: The first 3 seconds must grab instant attention.
4. Language tone: {language.upper()} (Natural Roman Hinglish - e.g. "School dance ke naam par bada scam!").
5. Return strictly valid JSON array without any markdown formatting.

JSON Schema:
[
  {{
    "start": 12.5,
    "end": 42.0,
    "title": "Main Curiosity Title (Max 60 chars)",
    "title_options": [
      "Curiosity Title 1 (Max 60 chars)",
      "Curiosity Title 2 (Question format)",
      "Curiosity Title 3 (Relatable punchline)"
    ],
    "hook_line": "HOOK LINE FOR FIRST 3 SECONDS (ALL CAPS)",
    "hook_options": [
      "HOOK OPTION 1 (Question/Surprise)",
      "HOOK OPTION 2 (Relatable Statement)",
      "HOOK OPTION 3 (Curiosity Gap)"
    ],
    "viral_score": 95,
    "viral_reason": "One punchy line explaining why this clip will retain viewers",
    "platforms": {{
      "youtube": {{
        "title": "High CTR YouTube Title #shorts",
        "description": "2-3 lines engaging description + CTA (Subscribe for daily clips!)",
        "hashtags": ["#shorts", "#viral", "#comedy", "#relatable"]
      }},
      "instagram": {{
        "title": "Instagram Reels Caption",
        "description": "Relatable caption + Tag a friend CTA",
        "hashtags": ["#reelsindia", "#explore", "#viralreels", "#funny"]
      }},
      "tiktok": {{
        "title": "TikTok Catchy Title",
        "description": "Short punchy caption + Follow for Part 2",
        "hashtags": ["#fyp", "#trending", "#viral", "#relatable"]
      }}
    }}
  }}
]

Transcript:
{full_transcript_str}
"""

    models_to_try = [model_name] + [m for m in MODEL_CANDIDATES if m != model_name]
    response = None
    last_err = None
    for m in models_to_try:
        try:
            print(f"[Gemini] Analyzing transcript using {m}...")
            response = client.models.generate_content(
                model=m,
                contents=prompt,
            )
            if response and response.text:
                print(f"[Gemini] Success with {m}")
                break
        except Exception as e:
            last_err = e
            print(f"[Gemini] Model {m} error: {e}. Trying fallback...")
            continue

    if not response or not response.text:
        print(f"[Gemini] All AI models failed or rate-limited ({last_err}). Falling back to heuristic clip selection.")
        return generate_heuristic_clips(transcript_segments, num_clips, min_len, max_len)

    try:
        cleaned = clean_json_text(response.text)
        clips = json.loads(cleaned)
        if not isinstance(clips, list):
            clips = [clips]
        return clips
    except Exception as parse_err:
        print(f"[Gemini] JSON parse error: {parse_err}. Falling back to heuristic clip selection.")
        return generate_heuristic_clips(transcript_segments, num_clips, min_len, max_len)

def generate_heuristic_clips(
    transcript_segments: List[Dict[str, Any]],
    num_clips: int = 1,
    min_len: int = 20,
    max_len: int = 60
) -> List[Dict[str, Any]]:
    """
    Intelligent heuristic fallback when Gemini API is unreachable or rate limited.
    Selects high-impact contiguous segments with complete sentences and hooks.
    """
    if not transcript_segments:
        return [{
            "start": 0.0,
            "end": 30.0,
            "title": "Viral Moment",
            "title_options": ["Viral Moment", "Wait For It!", "Best Scene"],
            "hook_line": "WATCH TILL END! 🔥",
            "hook_options": ["WATCH TILL END! 🔥", "WAIT FOR IT... 💀", "UNREAL! 😱"],
            "viral_score": 90,
            "viral_reason": "Curated dialogue highlight.",
            "platforms": {
                "youtube": {"title": "Viral Moment #shorts", "description": "Subscribe for daily reels!", "hashtags": ["#shorts", "#viral"]},
                "instagram": {"title": "Viral Moment", "description": "Tag a friend! 😂👇", "hashtags": ["#reels", "#explore"]},
                "tiktok": {"title": "Viral Moment", "description": "Wait for this 😭", "hashtags": ["#fyp", "#trending"]}
            }
        }]

    total_dur = transcript_segments[-1]["end"]
    clips = []
    stride = max(30.0, total_dur / (num_clips + 1))

    for i in range(num_clips):
        target_start = max(5.0, (i + 1) * stride - 15.0)
        target_end = min(total_dur, target_start + min(45, max_len))

        matching_segs = [s for s in transcript_segments if s["end"] >= target_start and s["start"] <= target_end]
        if matching_segs:
            c_start = matching_segs[0]["start"]
            c_end = matching_segs[-1]["end"]
            clip_text = " ".join(s.get("text", "") for s in matching_segs).strip()
        else:
            c_start = target_start
            c_end = target_end
            clip_text = "Viral Highlight"

        words = clip_text.split()
        lead = " ".join(words[:6]) if words else f"Highlight Part {i+1}"
        clean_title = re.sub(r'[^\w\s]', '', lead).strip()
        if len(clean_title) > 35:
            clean_title = clean_title[:35].rsplit(' ', 1)[0]

        clips.append({
            "start": round(c_start, 2),
            "end": round(c_end, 2),
            "title": clean_title or f"Viral Part {i+1}",
            "title_options": [
                clean_title or f"Viral Part {i+1}",
                f"Wait For This Scene #{i+1} 💀",
                f"Most Relatable Part #{i+1} 😂"
            ],
            "hook_line": "WATCH TILL END! 🔥",
            "hook_options": [
                "WATCH TILL END! 🔥",
                "WAIT FOR IT... 💀",
                "DON'T MISS THIS! 😱"
            ],
            "viral_score": 91,
            "viral_reason": "High verbal pacing and engaging story flow.",
            "platforms": {
                "youtube": {
                    "title": f"{clean_title} #shorts",
                    "description": "Must watch highlight from this episode!\n\nSubscribe for daily clips!",
                    "hashtags": ["#shorts", "#viral", "#trending", "#relatable"]
                },
                "instagram": {
                    "title": clean_title,
                    "description": "Tag that one friend who needs to see this! 😂👇\nFollow for more daily reels!",
                    "hashtags": ["#reels", "#explore", "#viral", "#trending", "#comedy"]
                },
                "tiktok": {
                    "title": clean_title,
                    "description": "Wait till you see what happens next 😭 #fyp",
                    "hashtags": ["#fyp", "#viral", "#foryou", "#trending"]
                }
            }
        })
    return clips

def resuggest_metadata(
    clip_record: Dict[str, Any],
    model_name: str = DEFAULT_MODEL,
    language: str = "hinglish"
) -> Dict[str, Any]:
    """
    Regenerates only titles, hooks, description, and hashtags for an existing clip without video rendering.
    """
    client = get_client()
    title = clip_record.get("title", "")
    reason = clip_record.get("viral_reason", "")
    existing_hook = clip_record.get("hook_line", "")

    prompt = f"""You are a viral social media strategist.
Generate fresh, high-CTR social media copy for this video clip:
Current Title: {title}
Context/Theme: {reason}
Current Hook: {existing_hook}
Language: {language}

Provide:
1. 3 new Curiosity Title options (max 60 chars, curiosity gap, no fake clickbait).
2. 3 new Hook Line options for the first 3 seconds (punchy, ALL-CAPS).
3. Fresh YouTube Shorts, Instagram Reels, and TikTok captions + 8-12 hashtags.
4. Updated Viral Score (1-100) and rationale.

Return strictly a valid JSON object:
{{
  "title_options": ["Title 1", "Title 2", "Title 3"],
  "hook_line": "PRIMARY HOOK LINE",
  "hook_options": ["Hook 1", "Hook 2", "Hook 3"],
  "viral_score": 96,
  "viral_reason": "High retention reason",
  "platforms": {{
    "youtube": {{
      "title": "Title #shorts",
      "description": "Description + CTA",
      "hashtags": ["#shorts", "#viral"]
    }},
    "instagram": {{
      "title": "Reels Caption",
      "description": "Caption + CTA",
      "hashtags": ["#reels", "#explore"]
    }},
    "tiktok": {{
      "title": "TikTok Title",
      "description": "Caption + CTA",
      "hashtags": ["#fyp", "#trending"]
    }}
  }}
}}
"""
    models_to_try = [model_name] + [m for m in MODEL_CANDIDATES if m != model_name]
    response = None
    for m in models_to_try:
        try:
            response = client.models.generate_content(model=m, contents=prompt)
            break
        except Exception:
            continue

    if not response or not response.text:
        return {}

    cleaned = clean_json_text(response.text)
    return json.loads(cleaned)

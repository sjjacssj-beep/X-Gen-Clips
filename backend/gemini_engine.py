import json
import os
import re
import time
from typing import List, Dict, Any, Tuple

DEFAULT_MODEL = "gemini-3.7-flash"
MODEL_CANDIDATES = ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-2.5-flash"]

def get_client(api_key: str = None):
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY set nahi hai! Settings mein jaakar API key daalo.")
    from google import genai
    return genai.Client(api_key=key)

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
            response = client.models.generate_content(
                model=m,
                contents=prompt,
            )
            break
        except Exception as e:
            last_err = e
            if "404" in str(e) or "not found" in str(e).lower() or "429" in str(e) or "quota" in str(e).lower():
                continue
            raise e

    if not response or not response.text:
        if last_err:
            raise last_err
        raise ValueError("Gemini API ne empty response diya.")

    cleaned = clean_json_text(response.text)
    clips = json.loads(cleaned)
    if not isinstance(clips, list):
        clips = [clips]

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

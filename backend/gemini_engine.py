import json
import os
import re
import time
from typing import List, Dict, Any, Tuple
from .script_sanitizer import sanitize_metadata_obj, sanitize_urdu_to_hinglish
from . import title_desc_engine

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

    if str(language).lower() == "english":
        lang_directive = """4. Language tone: Strictly FLUENT ENGLISH. All titles, hooks, descriptions, and hashtags must be in English.
5. SCRIPT ENFORCEMENT: Never output Urdu or Hindi script; use English."""
    else:
        lang_directive = """4. Language tone: Strictly NATURAL ROMAN HINGLISH (English alphabet only, e.g. 'Bhai ye twist dekho', 'Lucia karte use', 'Ek tagda hits').
5. SCRIPT ENFORCEMENT: ABSOLUTELY NEVER output Urdu, Arabic, or Perso-Arabic script. Urdu language is completely banned. All Hindi and gaming speech must use the standard Latin English alphabet."""

    prompt = f"""You are a world-class viral video editor (Alex Hormozi / MrBeast style).
Analyze the following transcript from a video. Pick the TOP {num_clips} most viral, engaging, funny, or insightful continuous moments suitable for vertical short-form reels (YouTube Shorts, Instagram Reels, TikTok).

Rules:
1. Duration: Each clip MUST be between {min_len} and {max_len} seconds.
2. Complete thought: Snap start and end to natural sentence boundaries (NEVER cut off mid-sentence).
3. Viral Hook: The first 3 seconds must grab instant attention.
{lang_directive}
6. Return strictly valid JSON array without any markdown formatting.

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
        return sanitize_metadata_obj(clips)
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
            clip_text = "Gaming Highlight"

        # Topic extraction & grounded title generation via title_desc_engine
        primary_topic, _ = title_desc_engine.extract_primary_topic({"title": "Gaming Highlight"}, clip_text)
        mood = title_desc_engine.detect_clip_mood(clip_text)
        title_variants = title_desc_engine.generate_3_titles(
            primary_topic=primary_topic,
            clip_theme=f"Moment #{i+1}",
            mood=mood,
            language="hinglish",
            emoji_level="low"
        )
        title_options = [t["title"] for t in title_variants]
        main_title = title_options[0]

        desc_variants = title_desc_engine.generate_2_descriptions(
            primary_topic=primary_topic,
            clip_summary=f"{primary_topic} ka insane scene dekh kar hosh ud jayenge",
            hashtags=[f"#{primary_topic.replace(' ', '')}", "#GamingShorts", "#Shorts"],
            language="hinglish",
            emoji_level="low"
        )
        main_desc = desc_variants[0]["text"]

        clips.append({
            "start": round(c_start, 2),
            "end": round(c_end, 2),
            "title": main_title,
            "title_options": title_options,
            "title_variants": title_variants,
            "description": main_desc,
            "description_options": desc_variants,
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
                    "title": f"{main_title} #shorts",
                    "description": main_desc,
                    "hashtags": ["#shorts", "#viral", "#trending", f"#{primary_topic.replace(' ', '')}"],
                    "title_options": title_options,
                    "description_options": [d["text"] for d in desc_variants]
                },
                "instagram": {
                    "title": main_title,
                    "description": f"{main_desc}\n\nTag that one friend who needs to see this! 😂👇",
                    "hashtags": ["#reels", "#explore", "#viral", "#trending"]
                },
                "tiktok": {
                    "title": main_title,
                    "description": f"{main_title}\nFollow for Part 2! 🚀 #fyp",
                    "hashtags": ["#fyp", "#viral", "#foryou", "#trending"]
                }
            }
        })
    return sanitize_metadata_obj(clips)

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

    primary_topic, _ = title_desc_engine.extract_primary_topic({"title": title}, reason)
    mood = title_desc_engine.detect_clip_mood(f"{title} {reason}")

    if response and response.text:
        try:
            cleaned = clean_json_text(response.text)
            parsed = json.loads(cleaned)
            # Validate or replace titles using title_desc_engine
            valid_titles = []
            for t_opt in parsed.get("title_options", []):
                ok, _ = title_desc_engine.validate_title(t_opt, [primary_topic], max_chars=60, allowed_lang=language)
                if ok:
                    valid_titles.append(t_opt)
            if len(valid_titles) < 3:
                gen_titles = title_desc_engine.generate_3_titles(primary_topic, reason[:20], mood, language=language)
                parsed["title_options"] = [t["title"] for t in gen_titles]
                parsed["title_variants"] = gen_titles
            else:
                parsed["title_options"] = valid_titles[:3]
                parsed["title_variants"] = [{"id": i+1, "title": t} for i, t in enumerate(valid_titles[:3])]

            descs = title_desc_engine.generate_2_descriptions(primary_topic, reason, parsed.get("platforms", {}).get("youtube", {}).get("hashtags", []), language=language)
            parsed["description_options"] = descs
            parsed["description"] = descs[0]["text"]
            parsed["title"] = parsed["title_options"][0]
            if "youtube" in parsed.get("platforms", {}):
                parsed["platforms"]["youtube"]["title_options"] = parsed["title_options"]
                parsed["platforms"]["youtube"]["description_options"] = [d["text"] for d in descs]
                parsed["platforms"]["youtube"]["description"] = descs[0]["text"]
            return sanitize_metadata_obj(parsed)
        except Exception as e:
            logger.warning(f"Failed to parse or ground resuggest response: {e}")

    # Fallback to local deterministic title & description generation
    title_vars = title_desc_engine.generate_3_titles(primary_topic, reason[:20] if reason else "Highlight", mood, language=language)
    desc_vars = title_desc_engine.generate_2_descriptions(primary_topic, reason or f"{primary_topic} insane highlight", [f"#{primary_topic.replace(' ', '')}", "#GamingShorts", "#Shorts"], language=language)
    t_opts = [t["title"] for t in title_vars]
    return sanitize_metadata_obj({
        "title": t_opts[0],
        "title_options": t_opts,
        "title_variants": title_vars,
        "description": desc_vars[0]["text"],
        "description_options": desc_vars,
        "hook_line": "WATCH TILL END! 🔥",
        "hook_options": ["WATCH TILL END! 🔥", "WAIT FOR IT... 💀", "DON'T MISS THIS! 😱"],
        "viral_score": 93,
        "viral_reason": reason or "High emotional pacing and strong hook retention.",
        "platforms": {
            "youtube": {
                "title": f"{t_opts[0]} #shorts",
                "description": desc_vars[0]["text"],
                "hashtags": [f"#{primary_topic.replace(' ', '')}", "#GamingShorts", "#Shorts", "#Viral"],
                "title_options": t_opts,
                "description_options": [d["text"] for d in desc_vars]
            },
            "instagram": {
                "title": t_opts[0],
                "description": f"{desc_vars[0]['text']}\n\nTag that one friend who needs to see this! 😂👇",
                "hashtags": ["#reels", "#explore", "#viral", "#trending"]
            },
            "tiktok": {
                "title": t_opts[0],
                "description": f"{t_opts[0]}\nFollow for Part 2! 🚀 #fyp",
                "hashtags": ["#fyp", "#viral", "#foryou", "#trending"]
            }
        }
    })

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import httpx
from .script_sanitizer import sanitize_metadata_obj, sanitize_urdu_to_hinglish
from . import title_desc_engine

logger = logging.getLogger("xgenclips.llm")

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_PROVIDERS = {
    "ollama": {
        "name": "Ollama (Local PC)",
        "enabled": True,
        "base_url": "http://localhost:11434/v1",
        "api_key": "",
        "model": "qwen2.5:3b",
        "max_context": 32768,
        "is_local": True,
        "description": "Zero cost, unlimited quota, 100% private on your machine.",
        "status": "ready",
        "last_error": "",
        "quota_used": 0
    },
    "groq": {
        "name": "Groq (Ultra-Fast Cloud)",
        "enabled": False,
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": "",
        "model": "llama-3.3-70b-versatile",
        "max_context": 32768,
        "is_local": False,
        "description": "Blazing fast inference (500+ tokens/sec). Free tier available.",
        "status": "not_configured",
        "last_error": "",
        "quota_used": 0
    },
    "cerebras": {
        "name": "Cerebras",
        "enabled": False,
        "base_url": "https://api.cerebras.ai/v1",
        "api_key": "",
        "model": "llama3.1-8b",
        "max_context": 8192,
        "is_local": False,
        "description": "High-throughput AI hardware accelerator cloud.",
        "status": "not_configured",
        "last_error": "",
        "quota_used": 0
    },
    "openrouter": {
        "name": "OpenRouter (Free Tiers)",
        "enabled": False,
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "max_context": 32768,
        "is_local": False,
        "description": "Access to community free-tier models (may train on prompts).",
        "status": "not_configured",
        "last_error": "",
        "quota_used": 0
    },
    "gemini": {
        "name": "Google Gemini",
        "enabled": True,
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key": "",
        "model": "gemini-3.8-flash",
        "max_context": 128000,
        "is_local": False,
        "description": "Google Gemini 3.8 Flash with massive context window.",
        "status": "ready",
        "last_error": "",
        "quota_used": 0
    }
}

DEFAULT_PRIORITY = ["ollama", "groq", "cerebras", "openrouter", "gemini"]

def clean_json_text(text: str) -> str:
    cleaned = text.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```")[1].split("```")[0].strip()
    return cleaned.strip()

def post_process_candidate(
    c: Dict[str, Any],
    video_context: Dict[str, Any],
    language: str = "hinglish"
) -> Dict[str, Any]:
    """Ensures candidate has 3 validated topic-grounded titles and 2 structured 4-line descriptions."""
    c_copy = dict(c)
    clip_text = c_copy.get("text", "") or c_copy.get("transcript", "")
    primary_topic, topic_kws = title_desc_engine.extract_primary_topic(video_context, clip_text)
    mood = title_desc_engine.detect_clip_mood(f"{clip_text} {c_copy.get('viral_reason', '')}")

    existing_titles = c_copy.get("title_options", [])
    valid_titles = []
    for t in existing_titles:
        if isinstance(t, str):
            ok, _ = title_desc_engine.validate_title(t, topic_kws, max_chars=60, allowed_lang=language)
            if ok and t not in valid_titles:
                valid_titles.append(t)

    if len(valid_titles) < 3:
        theme = c_copy.get("theme") or c_copy.get("title") or c_copy.get("hook_line") or "Insane Moment"
        theme = re.sub(r'[^a-zA-Z0-9\s]', '', str(theme)).strip()[:24]
        gen_titles = title_desc_engine.generate_3_titles(
            primary_topic=primary_topic,
            clip_theme=theme or "Highlight",
            mood=mood,
            language=language
        )
        c_copy["title_options"] = [t["title"] for t in gen_titles]
        c_copy["title_variants"] = gen_titles
        c_copy["title"] = c_copy["title_options"][0]
    else:
        c_copy["title_options"] = valid_titles[:3]
        c_copy["title_variants"] = [{"id": i+1, "title": t} for i, t in enumerate(valid_titles[:3])]
        c_copy["title"] = valid_titles[0]

    # Generate 2 distinct 4-line structured descriptions
    summary = c_copy.get("viral_reason") or f"{primary_topic} ka insane scene dekh kar hosh ud jayenge"
    tags = c_copy.get("hashtags", [])
    desc_variants = title_desc_engine.generate_2_descriptions(
        primary_topic=primary_topic,
        clip_summary=summary,
        hashtags=tags,
        language=language
    )
    c_copy["description_options"] = desc_variants
    c_copy["description"] = desc_variants[0]["text"]

    yt_meta = c_copy.get("platforms", {}).get("youtube", {}) if isinstance(c_copy.get("platforms"), dict) else {}
    yt_meta["title"] = f"{c_copy['title']} #shorts" if not c_copy['title'].lower().endswith("#shorts") else c_copy['title']
    yt_meta["description"] = desc_variants[0]["text"]
    yt_meta["hashtags"] = tags or [f"#{primary_topic.replace(' ', '')}", "#GamingShorts", "#Shorts"]
    yt_meta["title_options"] = c_copy["title_options"]
    yt_meta["description_options"] = [d["text"] for d in desc_variants]

    c_copy["platforms"] = {
        "youtube": yt_meta,
        "instagram": {
            "title": c_copy["title"],
            "description": f"{desc_variants[0]['text']}\n\nTag that one friend! 😂👇",
            "hashtags": (tags[:5] if tags else ["#reels", "#explore", "#viral"])
        },
        "tiktok": {
            "title": c_copy["title"],
            "description": f"{c_copy['title']}\nFollow for Part 2! 🚀 #fyp",
            "hashtags": (tags[:5] if tags else ["#fyp", "#viral", "#foryou"])
        }
    }
    return c_copy

def get_cache_path(prompt: str, model: str) -> Path:
    h = hashlib.sha256(f"{model}:{prompt}".encode("utf-8")).hexdigest()
    return CACHE_DIR / f"llm_{h}.json"

def read_llm_cache(prompt: str, model: str) -> Optional[Dict[str, Any]]:
    p = get_cache_path(prompt, model)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None

def write_llm_cache(prompt: str, model: str, data: Dict[str, Any]):
    p = get_cache_path(prompt, model)
    try:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to write LLM cache: {e}")

class LLMProviderChain:
    def __init__(self, settings_path: Optional[Path] = None):
        self.settings_path = settings_path or (BASE_DIR / "settings.json")
        self.providers: Dict[str, Dict[str, Any]] = {}
        self.priority: List[str] = list(DEFAULT_PRIORITY)
        self.load_config()

    def load_config(self):
        """Loads provider credentials and priority from settings.json."""
        self.providers = {k: dict(v) for k, v in DEFAULT_PROVIDERS.items()}
        
        # Read from environment or settings.json
        gemini_env = os.environ.get("GEMINI_API_KEY", "")
        if gemini_env:
            self.providers["gemini"]["api_key"] = gemini_env
            self.providers["gemini"]["status"] = "ready"

        if self.settings_path.exists():
            try:
                s = json.loads(self.settings_path.read_text(encoding="utf-8"))
                saved_provs = s.get("llm_providers", {})
                for k, pdata in saved_provs.items():
                    if k in self.providers:
                        self.providers[k].update(pdata)
                
                saved_priority = s.get("llm_priority", [])
                if saved_priority and isinstance(saved_priority, list):
                    # Ensure only known providers
                    self.priority = [p for p in saved_priority if p in self.providers]
                    for p in DEFAULT_PRIORITY:
                        if p not in self.priority:
                            self.priority.append(p)
                
                # If Gemini API key is saved in main settings
                if s.get("gemini_api_key") and not self.providers["gemini"]["api_key"]:
                    self.providers["gemini"]["api_key"] = s["gemini_api_key"]
                    self.providers["gemini"]["status"] = "ready"
            except Exception as e:
                logger.warning(f"Could not parse LLM settings: {e}")

    def save_config(self):
        """Persists LLM configuration to settings.json."""
        if not self.settings_path.exists():
            curr = {}
        else:
            try:
                curr = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except Exception:
                curr = {}

        curr["llm_providers"] = self.providers
        curr["llm_priority"] = self.priority
        self.settings_path.write_text(json.dumps(curr, indent=2, ensure_ascii=False), encoding="utf-8")

    def test_provider(self, provider_id: str) -> Dict[str, Any]:
        """Tests connectivity and measures latency to a specific provider."""
        if provider_id not in self.providers:
            return {"success": False, "message": f"Provider '{provider_id}' anjaan hai."}

        prov = self.providers[provider_id]
        base_url = prov.get("base_url", "").rstrip("/")
        api_key = prov.get("api_key", "").strip()
        model = prov.get("model", "")

        if not prov.get("is_local") and not api_key:
            return {"success": False, "message": "API key required hai. Kripya key dalein."}

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        test_payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a test ping bot. Respond only with JSON."},
                {"role": "user", "content": "Respond: {\"status\": \"ok\"}"}
            ],
            "response_format": {"type": "json_object"}
        }

        t0 = time.time()
        timeout = 60.0 if prov.get("is_local") else 20.0
        try:
            with httpx.Client(timeout=timeout) as client:
                endpoint = f"{base_url}/chat/completions"
                resp = client.post(endpoint, json=test_payload, headers=headers)
                latency_ms = int((time.time() - t0) * 1000)

                if resp.status_code == 200:
                    prov["status"] = "ready"
                    prov["last_error"] = ""
                    self.save_config()
                    return {
                        "success": True,
                        "latency_ms": latency_ms,
                        "model": model,
                        "message": f"✓ Connection Successful! ({latency_ms}ms latency)"
                    }
                else:
                    err_text = resp.text[:200]
                    prov["status"] = "error"
                    prov["last_error"] = f"HTTP {resp.status_code}: {err_text}"
                    self.save_config()
                    return {
                        "success": False,
                        "latency_ms": latency_ms,
                        "message": f"HTTP {resp.status_code}: {err_text}"
                    }
        except Exception as e:
            prov["status"] = "error"
            prov["last_error"] = str(e)
            self.save_config()
            return {"success": False, "message": f"Connection failed: {str(e)}"}

    def generate_chat_completion(
        self,
        messages: List[Dict[str, str]],
        response_format: Optional[Dict[str, str]] = None,
        temperature: float = 0.7,
        use_cache: bool = True
    ) -> Tuple[Optional[str], str]:
        """
        Executes chat completion with automatic fallback across the provider chain.
        Returns (content_str, provider_used).
        """
        prompt_key = json.dumps(messages, sort_keys=True)
        
        # Check disk cache first
        if use_cache:
            for p_id in self.priority:
                prov = self.providers.get(p_id)
                if prov and prov.get("enabled"):
                    cached = read_llm_cache(prompt_key, prov.get("model", ""))
                    if cached and "content" in cached:
                        return cached["content"], f"{p_id} (cache)"

        # Fallback loop
        errors = []
        for p_id in self.priority:
            prov = self.providers.get(p_id)
            if not prov or not prov.get("enabled"):
                continue

            # Skip non-local providers with missing API keys
            if not prov.get("is_local") and not prov.get("api_key"):
                continue

            base_url = prov["base_url"].rstrip("/")
            api_key = prov.get("api_key", "").strip()
            model = prov["model"]

            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            payload: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature
            }
            if response_format:
                payload["response_format"] = response_format

            timeout = 120.0 if prov.get("is_local") else 45.0
            try:
                with httpx.Client(timeout=timeout) as client:
                    endpoint = f"{base_url}/chat/completions"
                    resp = client.post(endpoint, json=payload, headers=headers)

                    if resp.status_code == 200:
                        data = resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            content = choices[0].get("message", {}).get("content", "")
                            prov["quota_used"] = prov.get("quota_used", 0) + 1
                            prov["status"] = "ready"
                            prov["last_error"] = ""
                            if use_cache:
                                write_llm_cache(prompt_key, model, {"content": content})
                            return content, p_id
                    elif resp.status_code in (429, 503):
                        # Rate limit or quota exhaustion: failover immediately
                        err_msg = f"HTTP {resp.status_code} (Rate Limit / Quota Exceeded)"
                        logger.warning(f"Provider '{p_id}' rate limited: {err_msg}. Failing over to next provider...")
                        prov["status"] = "rate_limited"
                        prov["last_error"] = err_msg
                        errors.append(f"{p_id}: {err_msg}")
                    else:
                        err_msg = f"HTTP {resp.status_code}: {resp.text[:150]}"
                        logger.warning(f"Provider '{p_id}' error: {err_msg}")
                        prov["status"] = "error"
                        prov["last_error"] = err_msg
                        errors.append(f"{p_id}: {err_msg}")
            except Exception as e:
                logger.warning(f"Provider '{p_id}' exception: {e}")
                prov["status"] = "error"
                prov["last_error"] = str(e)
                errors.append(f"{p_id}: {str(e)}")

        logger.error(f"All LLM providers failed: {'; '.join(errors)}")
        return None, "none"

    def analyze_viral_candidates(
        self,
        candidates: List[Dict[str, Any]],
        video_context: Dict[str, Any],
        language: str = "hinglish"
    ) -> List[Dict[str, Any]]:
        """
        Sends candidate moments to the active LLM chain to generate viral metadata.
        Guarantees structured JSON return.
        """
        if str(language).lower() == "english":
            lang_rule = "ALL titles, hooks, descriptions, and hashtags MUST be in fluent English."
            sys_msg = "You are an elite short-form video viral retention expert. Respond strictly in valid JSON in fluent English."
        else:
            lang_rule = "ALL titles, hooks, descriptions, and hashtags MUST be in natural Roman Hinglish (English alphabet only, e.g. 'Bhai ye scene dekho', 'Lucia karte use'). ABSOLUTELY NEVER under any circumstances output Urdu, Arabic, or Perso-Arabic characters. Urdu language is completely banned."
            sys_msg = "You are an elite short-form video viral retention expert. Respond strictly in valid JSON in Roman Hinglish. Never use Urdu/Arabic script."

        prompt = f"""You are a master viral YouTube Shorts & Reels producer.
Analyze these {len(candidates)} candidate moments extracted from the video:
Video Title: {video_context.get('title', 'Video')}
Category: {video_context.get('category', 'Gaming/Entertainment')}

Candidates to evaluate:
{json.dumps(candidates, indent=2, ensure_ascii=False)}

For each candidate, respond with a JSON array where each object has:
- "id": candidate id (integer)
- "viral_score": integer 1 to 100
- "viral_reason": 1 punchy line explaining why this moment will hook viewers
- "hook_line": Attention-grabbing Curiosity Hook for the first 3 seconds (UPPERCASE)
- "title_options": Array of 3 click-worthy curiosity titles (under 50 chars)
- "description": High-engagement social caption with CTA
- "hashtags": Array of 8-12 viral hashtags (e.g. #shorts, #viral, #gaming)
- "emoji_plan": 2-3 suitable emoji for word pop subtitles

CRITICAL SCRIPT & LANGUAGE DIRECTIVE:
{lang_rule}

Return ONLY a valid JSON array of evaluated candidates."""

        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt}
        ]

        content, prov_used = self.generate_chat_completion(
            messages,
            response_format={"type": "json_object"} if "ollama" in self.priority else None,
            temperature=0.7
        )

        if content:
            try:
                # Clean any markdown code blocks
                clean_json = content.strip()
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()
                
                parsed = json.loads(clean_json)
                c_list = parsed.get("candidates", []) if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])
                if c_list:
                    processed = [post_process_candidate(c, video_context, language) for c in c_list]
                    return sanitize_metadata_obj(processed)
            except Exception as e:
                logger.error(f"Failed to parse LLM JSON from {prov_used}: {e}")

        # Fallback heuristic generation if all providers fail
        logger.info("Using local algorithmic fallback for viral metadata packaging...")
        results = [post_process_candidate(c, video_context, language) for c in candidates]
        return sanitize_metadata_obj(results)

    def pick_clips_and_metadata(
        self,
        transcript_segments: List[Dict[str, Any]],
        num_clips: int = 1,
        min_len: int = 20,
        max_len: int = 60,
        language: str = "hinglish"
    ) -> List[Dict[str, Any]]:
        """
        Picks viral clips and generates complete metadata using the active LLM provider chain
        (prioritizing local Ollama qwen2.5:3b). Falls back to heuristic generation if all providers fail.
        """
        from . import gemini_engine

        # Format transcript with timestamps
        sample_text = []
        for s in transcript_segments:
            start_m = int(s["start"] // 60)
            start_s = int(s["start"] % 60)
            sample_text.append(f"[{start_m:02d}:{start_s:02d}] {s.get('text', '')}")
        full_transcript_str = "\n".join(sample_text)

        # Context truncation guard: keep up to 28,000 characters so local Ollama / models stay well within limits
        if len(full_transcript_str) > 28000:
            full_transcript_str = full_transcript_str[:28000] + "\n...[Transcript truncated for context window]..."

        if str(language).lower() in ("english", "en"):
            lang_directive = """4. Language tone: Strictly FLUENT ENGLISH. All titles, hooks, descriptions, and hashtags must be in English.
5. SCRIPT ENFORCEMENT: Never output Urdu or Hindi script; use English."""
            sys_msg = "You are a master viral YouTube Shorts & Reels producer. Return strictly valid JSON array in fluent English."
        else:
            lang_directive = """4. Language tone: Strictly NATURAL ROMAN HINGLISH (English alphabet only, e.g. 'Bhai ye scene dekho', 'Lucia karte use', 'Ek tagda hits').
5. SCRIPT ENFORCEMENT: ABSOLUTELY NEVER output Urdu, Arabic, or Perso-Arabic script. Urdu language is completely banned. All Hindi and gaming speech must use the standard Latin English alphabet."""
            sys_msg = "You are a master viral YouTube Shorts & Reels producer. Return strictly valid JSON array in Roman Hinglish. Never use Urdu/Arabic characters."

        prompt = f"""Analyze the following transcript from a video. Pick the TOP {num_clips} most viral, engaging, funny, or insightful continuous moments suitable for vertical short-form reels (YouTube Shorts, Instagram Reels, TikTok).

Rules:
1. Duration: Each clip MUST be between {min_len} and {max_len} seconds.
2. Complete thought: Snap start and end to natural sentence boundaries (NEVER cut off mid-sentence).
3. Viral Hook: The first 3 seconds must grab instant attention.
{lang_directive}
6. Return strictly valid JSON array without any markdown formatting or commentary.

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
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt}
        ]

        logger.info(f"Generating viral clips using LLM chain (priority: {self.priority})...")
        content, prov_used = self.generate_chat_completion(
            messages,
            temperature=0.7,
            use_cache=True
        )

        if content:
            try:
                cleaned = clean_json_text(content)
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict):
                    for k in ("clips", "candidates", "data", "results"):
                        if k in parsed and isinstance(parsed[k], list):
                            parsed = parsed[k]
                            break
                    if isinstance(parsed, dict):
                        parsed = [parsed]
                if isinstance(parsed, list) and len(parsed) > 0:
                    validated = []
                    for idx, c in enumerate(parsed):
                        if not isinstance(c, dict):
                            continue
                        c["id"] = idx + 1
                        c["start"] = max(0.0, float(c.get("start", 0.0)))
                        c["end"] = max(c["start"] + 5.0, float(c.get("end", c["start"] + 30.0)))
                        c["duration"] = round(c["end"] - c["start"], 2)
                        validated.append(c)
                    if validated:
                        logger.info(f"Successfully generated {len(validated)} clips with provider '{prov_used}'")
                        video_context = {"title": "Gaming Highlight", "category": "Gaming"}
                        processed = [post_process_candidate(c, video_context, language) for c in validated]
                        return sanitize_metadata_obj(processed)
            except Exception as e:
                logger.warning(f"Failed to parse LLM JSON from '{prov_used}': {e}. Falling back to heuristic clips.")

        # Fallback to heuristic clips
        logger.info("Using algorithmic heuristic clip selection fallback...")
        return gemini_engine.generate_heuristic_clips(transcript_segments, num_clips, min_len, max_len)

    def get_active_provider_status(self) -> Dict[str, Any]:
        """Returns the status and connectivity of the highest priority enabled provider."""
        self.load_config()
        for p_id in self.priority:
            prov = self.providers.get(p_id)
            if not prov or not prov.get("enabled"):
                continue

            # Skip non-local providers with empty API key
            if not prov.get("is_local") and not prov.get("api_key"):
                continue

            test_res = self.test_provider(p_id)
            return {
                "provider": p_id,
                "name": prov.get("name", p_id.title()),
                "model": prov.get("model", ""),
                "status": "connected" if test_res["success"] else "error",
                "latency_ms": test_res.get("latency_ms", 0),
                "message": test_res.get("message", ""),
                "is_local": prov.get("is_local", False)
            }

        return {
            "provider": "none",
            "name": "No Provider Configured",
            "model": "",
            "status": "not_configured",
            "latency_ms": 0,
            "message": "Settings mein ja kar AI Provider enable karein.",
            "is_local": False
        }

# Singleton chain instance
llm_chain = LLMProviderChain()

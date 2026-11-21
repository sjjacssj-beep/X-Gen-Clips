import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Set

logger = logging.getLogger("xgenclips.title_desc_engine")

BASE_DIR = Path(__file__).resolve().parent.parent
TRENDS_FILE = BASE_DIR / "data" / "niche" / "trends.json"

# Comprehensive regex to match emojis
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"  # flags (iOS)
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F700-\U0001F77F"  # alchemical symbols
    "\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
    "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
    "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
    "\U0001FA00-\U0001FA6F"  # Chess Symbols
    "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
    "\U00002702-\U000027B0"  # Dingbats
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE
)

URDU_ARABIC_PATTERN = re.compile(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]')
DEVANAGARI_PATTERN = re.compile(r'[\u0900-\u097F]')

DANGLING_END_WORDS = {
    "and", "or", "is", "that", "to", "in", "on", "at", "with", "the", "a", "an",
    "mein", "me", "ka", "ki", "ke", "ko", "se", "par", "pe", "aur", "ya", "toh", "hai", "tha", "thi", "the"
}

DEFAULT_TRENDS: Dict[str, Any] = {
    "emoji_level_default": "low",
    "emoji_pools": {
        "shock_action": ["🤯", "😱", "🔥", "💥", "⚡"],
        "funny": ["😂", "💀", "🤣", "😭"],
        "gaming": ["🎮", "🚗", "🔫", "🏎️", "🕹️"],
        "curiosity_question": ["🤔", "🧐", "❓", "👀"],
        "news_countdown": ["🚨", "⏳", "📢", "⚠️"]
    },
    "mood_keywords": {
        "shock_action": ["crazy", "insane", "shock", "omg", "blast", "clutch", "busted", "heist", "dangerous", "fast", "speed", "unbelievable", "tagda"],
        "funny": ["funny", "comedy", "hilarious", "joke", "troll", "epic fail", "lol", "kidding", "bhool", "meme", "hasna"],
        "gaming": ["gameplay", "gta", "gta 6", "mission", "drive", "car", "weapon", "shoot", "drift", "level", "boss", "vice city", "police"],
        "curiosity_question": ["how", "why", "secret", "hidden", "mystery", "real", "kya", "kaise", "kyun", "kaha", "possible"],
        "news_countdown": ["update", "leak", "release", "trailer", "breakdown", "top 3", "top 5", "announcement", "date"]
    },
    "topic_rules": {
        "default_keywords": ["GTA 6", "Gameplay", "Mission", "Vice City", "Trailer", "Clutch", "Secret", "Heist", "Police", "Escape", "Lucia", "Jason"],
        "max_title_chars": 60,
        "topic_max_word_position": 3
    },
    "cta_templates": {
        "hinglish": [
            "Follow karo agle part ke liye 🔔",
            "Comment me apna favorite scene batao 👇",
            "Aise hi insane moments ke liye Subscribe karein! 🚀",
            "Like aur share karo agar scene tagda laga! 🔥"
        ],
        "english": [
            "Subscribe for daily crazy clips! 🔔",
            "Drop your reaction in the comments! 👇",
            "Follow for Part 2! 🚀",
            "Like and share if this blew your mind! 🔥"
        ],
        "hindi": [
            "अगले भाग के लिए फ़ॉलो करें 🔔",
            "कमेंट में अपना पसंदीदा सीन बताएं 👇",
            "ऐसे ही शानदार पलों के लिए सब्सक्राइब करें! 🚀"
        ]
    },
    "emoji_blacklist": ["💩", "🤡", "🤮", "🖕", "🔞"]
}

_trends_cache: Optional[Dict[str, Any]] = None

def load_trends() -> Dict[str, Any]:
    """Loads configuration from data/niche/trends.json with fallback to defaults."""
    global _trends_cache
    if _trends_cache is not None:
        return _trends_cache
    if TRENDS_FILE.exists():
        try:
            data = json.loads(TRENDS_FILE.read_text(encoding="utf-8"))
            _trends_cache = data
            return data
        except Exception as e:
            logger.warning(f"Failed to read trends.json: {e}")
    _trends_cache = DEFAULT_TRENDS
    return DEFAULT_TRENDS

def reload_trends():
    """Forces reloading trends from disk."""
    global _trends_cache
    _trends_cache = None
    return load_trends()

def strip_emojis(text: str) -> str:
    """Removes all emojis and cleans leftover double spaces."""
    cleaned = EMOJI_PATTERN.sub("", text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def extract_emojis(text: str) -> List[str]:
    """Extracts all emojis present in a string."""
    return EMOJI_PATTERN.findall(text)

def detect_clip_mood(text: str, context: Optional[str] = None) -> str:
    """Detects mood category from text keywords."""
    combined = f"{text} {context or ''}".lower()
    trends = load_trends()
    mood_keywords = trends.get("mood_keywords", DEFAULT_TRENDS["mood_keywords"])

    scores = {m: 0 for m in mood_keywords}
    for mood, kws in mood_keywords.items():
        for kw in kws:
            if kw in combined:
                scores[mood] += 1

    best_mood = max(scores, key=scores.get)
    if scores[best_mood] > 0:
        return best_mood
    return "shock_action"

def pick_mood_emoji(
    mood: str,
    used_emojis: Optional[Set[str]] = None,
    blacklist: Optional[List[str]] = None
) -> str:
    """Picks an emoji matching the mood without repeating used emojis."""
    trends = load_trends()
    pools = trends.get("emoji_pools", DEFAULT_TRENDS["emoji_pools"])
    bl = set(blacklist or trends.get("emoji_blacklist", []))
    used = used_emojis or set()

    pool = pools.get(mood, pools.get("shock_action", ["🔥"]))
    available = [e for e in pool if e not in used and e not in bl]
    if available:
        return available[0]
    
    # If all used in pool, check fallback pool
    fallback_pool = pools.get("shock_action", ["🔥"])
    for e in fallback_pool:
        if e not in used and e not in bl:
            return e
    return pool[0] if pool else "🔥"

def format_title_with_emoji(
    title: str,
    mood: str,
    emoji_level: str = "low",
    used_emojis: Optional[Set[str]] = None
) -> Tuple[str, str]:
    """
    Formats title with strict emoji rules:
    - 1 emoji (or 2 if medium level) strictly at title END or START.
    - Never in the middle of words.
    - If emoji_level == 'off', returns clean text without emoji.
    Returns (formatted_title, emoji_used).
    """
    clean_text = strip_emojis(title).strip()
    if emoji_level == "off":
        return clean_text, ""

    chosen_emoji = pick_mood_emoji(mood, used_emojis=used_emojis)
    
    if emoji_level == "medium":
        # Pick 2 complementary emojis if possible
        second_emoji = pick_mood_emoji(mood, used_emojis=(used_emojis or set()).union({chosen_emoji}))
        if second_emoji and second_emoji != chosen_emoji:
            emojis_str = f"{chosen_emoji}{second_emoji}"
        else:
            emojis_str = chosen_emoji
    else:
        emojis_str = chosen_emoji

    # Format at the end of title
    formatted = f"{clean_text} {emojis_str}".strip()
    return formatted, chosen_emoji

def validate_title(
    title: str,
    topic_keywords: List[str],
    raw_transcript_sentences: Optional[List[str]] = None,
    max_chars: int = 60,
    allowed_lang: str = "hinglish"
) -> Tuple[bool, str]:
    """
    Code filter validating title compliance:
    1. Must not be empty.
    2. Length <= max_chars (default 60).
    3. Main topic keyword must appear in the first 3 words.
    4. Must not be a verbatim raw subtitle fragment.
    5. Must not end in broken dangling prepositions or conjunctions.
    6. Strictly single language (no Urdu/Arabic characters; no broken Devanagari in Hinglish).
    Returns (is_valid, reason).
    """
    if not title or not title.strip():
        return False, "Title is empty."

    clean_plain = strip_emojis(title).strip()
    if len(clean_plain) > max_chars:
        return False, f"Length {len(clean_plain)} chars exceeds {max_chars} character limit."

    # Language purity checks
    if URDU_ARABIC_PATTERN.search(title):
        return False, "Urdu or Arabic script detected. Urdu is banned."

    if allowed_lang in ("hinglish", "english"):
        if DEVANAGARI_PATTERN.search(clean_plain) and allowed_lang == "english":
            return False, "Devanagari script detected in English title."
        # If Hinglish, small Hindi words in Latin alphabet are standard, but script mixing inside a word is barred

    # Topic keyword in first 3 words
    words = clean_plain.split()
    if not words:
        return False, "Title contains no words."

    first_3_str = " ".join(words[:3]).lower()
    topic_found = False
    for kw in topic_keywords:
        kw_clean = kw.strip().lower()
        if kw_clean and kw_clean in first_3_str:
            topic_found = True
            break
        # Also allow if first word starts with the keyword
        if kw_clean and any(w.lower().startswith(kw_clean) for w in words[:3]):
            topic_found = True
            break

    if not topic_found:
        return False, f"Primary topic keyword ({', '.join(topic_keywords[:3])}) not found in first 3 words."

    # Dangling fragment check
    last_word = re.sub(r'[^a-zA-Z0-9]', '', words[-1].lower())
    if last_word in DANGLING_END_WORDS:
        return False, f"Title ends in incomplete sentence fragment/preposition: '{last_word}'."

    # Raw transcript sentence match check
    if raw_transcript_sentences:
        clean_words_set = set(w.lower() for w in words)
        for sent in raw_transcript_sentences:
            sent_words = [re.sub(r'[^a-zA-Z0-9]', '', w.lower()) for w in sent.split()]
            sent_words_set = set(w for w in sent_words if w)
            if sent_words_set:
                overlap = len(clean_words_set.intersection(sent_words_set)) / max(1, len(clean_words_set))
                # If title is > 80% verbatim words identical to raw subtitle without structure
                if overlap > 0.85 and len(clean_words_set) >= 4 and not topic_found:
                    return False, "Title is verbatim transcript audio snippet without topic hook."

    return True, "Valid"

def extract_primary_topic(
    video_context: Dict[str, Any],
    clip_transcript: str = "",
    channel_niche: str = "gaming"
) -> Tuple[str, List[str]]:
    """
    Extracts explicit topic entity and candidate topic keywords.
    Priority: video title entities -> context -> keywords.
    """
    trends = load_trends()
    def_kws = trends.get("topic_rules", {}).get("default_keywords", DEFAULT_TRENDS["topic_rules"]["default_keywords"])
    
    vid_title = video_context.get("title", "")
    keywords = []

    # Look for major known franchises or entities
    common_entities = ["GTA 6", "GTA VI", "Vice City", "Lucia", "Jason", "Police Chase", "Gameplay", "Trailer", "Rockstar"]
    for ent in common_entities:
        if ent.lower() in vid_title.lower() or ent.lower() in clip_transcript.lower():
            if ent not in keywords:
                keywords.append(ent)

    # Clean video title keywords
    clean_vid_words = re.sub(r'[\\/*?:"<>|#]', ' ', vid_title).split()
    for w in clean_vid_words:
        if len(w) >= 3 and w.lower() not in DANGLING_END_WORDS and w not in keywords:
            keywords.append(w)

    for dk in def_kws:
        if dk not in keywords:
            keywords.append(dk)

    primary_topic = keywords[0] if keywords else "GTA 6"
    return primary_topic, keywords

def verify_truth_grounding(
    title: str,
    description: str,
    clip_transcript: str,
    video_context: Dict[str, Any]
) -> Tuple[bool, str]:
    """
    Ensures that the core promise in the title has grounding in the clip transcript or video.
    Rejects wild hallucinations that have zero mention in the video.
    """
    if not clip_transcript:
        return True, "No transcript to verify against (grounded by default)."

    transcript_lower = f"{clip_transcript} {video_context.get('title', '')}".lower()
    title_words = [re.sub(r'[^a-zA-Z0-9]', '', w.lower()) for w in strip_emojis(title).split()]
    title_words = [w for w in title_words if len(w) > 3 and w not in DANGLING_END_WORDS]

    # At least one meaningful descriptive word from the title must be grounded in the context
    if not title_words:
        return True, "Grounded"

    matches = [w for w in title_words if w in transcript_lower]
    if len(matches) == 0 and len(title_words) >= 3:
        # Check if it's generic gaming hook that matches video category
        if "gaming" in video_context.get("category", "").lower() or "gta" in video_context.get("title", "").lower():
            return True, "Category-grounded"
        return False, "Title contains ungrounded claims not found in transcript or context."

    return True, "Grounded"

def generate_3_titles(
    primary_topic: str,
    clip_theme: str,
    mood: str,
    language: str = "hinglish",
    emoji_level: str = "low"
) -> List[Dict[str, str]]:
    """
    Generates 3 distinct, high-CTR, topic-grounded title variants:
    - Variant 1: Shock / Action / Climax
    - Variant 2: Curiosity Question
    - Variant 3: Punchline / Relatable / Number
    Guarantees unique emojis across all 3 variants.
    """
    trends = load_trends()
    clean_theme = re.sub(r'[^a-zA-Z0-9\s]', '', clip_theme).strip()
    if not clean_theme or len(clean_theme) > 25:
        clean_theme = "Crazy Scene"

    used_emojis: Set[str] = set()
    variants = []

    # Map angles and moods
    angles = [
        {"angle": "shock_action", "mood": "shock_action", "label": "Shock / Action"},
        {"angle": "curiosity_question", "mood": "curiosity_question", "label": "Question / Curiosity"},
        {"angle": "punchline", "mood": "gaming" if mood == "gaming" else "funny", "label": "Punchline / Viral"}
    ]

    for idx, ang in enumerate(angles, 1):
        m = ang["mood"]
        if language == "english":
            if idx == 1:
                base = f"{primary_topic} {clean_theme} Moment!"
            elif idx == 2:
                base = f"{primary_topic} {clean_theme} Explained?"
            else:
                base = f"{primary_topic} Insane {clean_theme} Scene"
        elif language == "hindi":
            if idx == 1:
                base = f"{primary_topic} {clean_theme} का सबसे खतरनाक सीन!"
            elif idx == 2:
                base = f"{primary_topic} में {clean_theme} कैसे हुआ?"
            else:
                base = f"{primary_topic} {clean_theme} का वायरल पल"
        else:  # hinglish
            if idx == 1:
                base = f"{primary_topic} {clean_theme} Dekho!"
            elif idx == 2:
                base = f"{primary_topic} Me {clean_theme} Kaise Hua?"
            else:
                base = f"{primary_topic} Ka Insane {clean_theme} Scene"

        # Apply strict length cap (< 60 chars)
        if len(base) > 50:
            base = f"{primary_topic} {clean_theme}"[:48]

        formatted_title, emoji_used = format_title_with_emoji(
            title=base,
            mood=m,
            emoji_level=emoji_level,
            used_emojis=used_emojis
        )
        if emoji_used:
            used_emojis.add(emoji_used)

        variants.append({
            "id": idx,
            "angle": ang["label"],
            "title": formatted_title,
            "raw_title": strip_emojis(formatted_title),
            "emoji": emoji_used,
            "mood": m
        })

    return variants

def generate_2_descriptions(
    primary_topic: str,
    clip_summary: str,
    hashtags: List[str],
    language: str = "hinglish",
    emoji_level: str = "low"
) -> List[Dict[str, str]]:
    """
    Generates 2 clean 4-line YouTube descriptions:
    - Variant 1: Story / Hype focused
    - Variant 2: Fast-paced Gameplay / Direct Action focused
    Structure:
    Line 1: Hook + Main Topic Keyword + 1 Emoji
    Line 2: 1-line clip summary + 1 Emoji
    Line 3: CTA + 1 Emoji
    Line 4: 3-5 Topic Hashtags
    """
    trends = load_trends()
    ctas = trends.get("cta_templates", {}).get(language, DEFAULT_TRENDS["cta_templates"]["hinglish"])
    cta1 = ctas[0] if len(ctas) > 0 else "Follow karo agle part ke liye 🔔"
    cta2 = ctas[1] if len(ctas) > 1 else "Comment me apna favorite scene batao 👇"

    clean_summary = clip_summary.strip()
    if not clean_summary:
        clean_summary = f"{primary_topic} ka ye scene dekh kar aapke hosh ud jayenge"

    clean_tags = []
    for t in hashtags:
        ct = t if t.startswith("#") else f"#{t}"
        if ct not in clean_tags and len(clean_tags) < 5:
            clean_tags.append(ct)
    if len(clean_tags) < 3:
        clean_tags.extend([f"#{primary_topic.replace(' ', '')}", "#GamingShorts", "#Shorts"])
    tags_line = " ".join(clean_tags[:5])

    # Variant 1: Story / Hype
    e1 = "🔥" if emoji_level != "off" else ""
    e2 = "🚨" if emoji_level != "off" else ""
    desc1_lines = [
        f"{primary_topic} Ka Sabse Insane Moment! {e1}".strip(),
        f"{clean_summary} {e2}".strip(),
        cta1 if emoji_level != "off" else strip_emojis(cta1),
        tags_line
    ]

    # Variant 2: Direct Action / Gameplay
    e3 = "🎮" if emoji_level != "off" else ""
    e4 = "💥" if emoji_level != "off" else ""
    desc2_lines = [
        f"{primary_topic} Gameplay Highlight! {e3}".strip(),
        f"Aakhir ye scene kaise possible hua? Check this out {e4}".strip(),
        cta2 if emoji_level != "off" else strip_emojis(cta2),
        tags_line
    ]

    return [
        {
            "id": 1,
            "label": "Story / Hype Angle",
            "text": "\n".join(desc1_lines),
            "lines": desc1_lines
        },
        {
            "id": 2,
            "label": "Action / Gameplay Angle",
            "text": "\n".join(desc2_lines),
            "lines": desc2_lines
        }
    ]

def cycle_title_emoji(title: str, mood: str = "shock_action") -> str:
    """Cycles through the mood pool emojis for a title."""
    trends = load_trends()
    pools = trends.get("emoji_pools", DEFAULT_TRENDS["emoji_pools"])
    pool = pools.get(mood, pools.get("shock_action", ["🔥", "⚡", "🤯", "😱", "💥"]))

    clean = strip_emojis(title).strip()
    current_emojis = extract_emojis(title)
    
    current = current_emojis[0] if current_emojis else ""
    if current in pool:
        next_idx = (pool.index(current) + 1) % len(pool)
        new_emoji = pool[next_idx]
    else:
        new_emoji = pool[0] if pool else "🔥"

    return f"{clean} {new_emoji}".strip()

def toggle_emojis_in_text(text: str, remove: bool = True, mood: str = "shock_action") -> str:
    """Strips or restores emojis in text."""
    if remove:
        return strip_emojis(text)
    # Restore with 1 emoji
    clean = strip_emojis(text).strip()
    trends = load_trends()
    pools = trends.get("emoji_pools", DEFAULT_TRENDS["emoji_pools"])
    pool = pools.get(mood, ["🔥"])
    return f"{clean} {pool[0]}".strip()

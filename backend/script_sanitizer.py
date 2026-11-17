import os
import re
from pathlib import Path
from typing import Dict, Any, List, Union, Tuple, Optional

URDU_WORD_MAP = {
    # Pronouns & Conjunctions
    'یہ': 'ye', 'وہ': 'woh', 'اگر': 'agar', 'آپ': 'aap', 'تم': 'tum', 'تو': 'toh', 'اور': 'aur',
    'کا': 'ka', 'کی': 'ki', 'کے': 'ke', 'کو': 'ko', 'سے': 'se', 'میں': 'mein', 'پر': 'par', 'پہ': 'pe',
    'اپنے': 'apne', 'اپنا': 'apna', 'अपनी': 'apni', 'ہم': 'hum', 'مرا': 'mera', 'میری': 'meri', 'میرے': 'mere',
    'تیرا': 'tera', 'تیری': 'teri', 'تیرے': 'tere', 'اس': 'is', 'ان': 'un', 'انہیں': 'unhein',
    # Verbs
    'کرتے': 'karte', 'کرتا': 'karta', 'کرتی': 'karti', 'کر': 'kar', 'کرو': 'karo', 'کریں': 'karein',
    'ہے': 'hai', 'ہیں': 'hain', 'تھا': 'tha', 'تھی': 'thi', 'تھے': 'the', 'ہو': 'ho', 'ہوا': 'hua', 'ہوئی': 'hui',
    'ہوگا': 'hoga', 'ہوگی': 'hogi', 'ہوں': 'hoon', 'رہے': 'rahe', 'رہا': 'raha', 'رہی': 'rahi',
    'دیکھو': 'dekho', 'دیکھیں': 'dekhein', 'دیکھا': 'dekha', 'دیکھ': 'dekh', 'دیکھتے': 'dekhte',
    'بول': 'bol', 'بولو': 'bolo', 'کہا': 'kaha', 'سنو': 'suno', 'آیا': 'aaya', 'گیا': 'gaya', 'جاؤ': 'jao',
    'پتا': 'pata', 'جان': 'jaan', 'پڑھ': 'padh', 'مار': 'maar', 'لے': 'le', 'لو': 'lo', 'دے': 'de', 'دو': 'do',
    # Common Nouns & Adjectives
    'ایک': 'ek', 'دو': 'do', 'تین': 'teen', 'چار': 'chaar', 'پانچ': 'paanch',
    'نہیں': 'nahi', 'نہ': 'na', 'بھائی': 'bhai', 'کیا': 'kya', 'کیوں': 'kyun', 'کیسے': 'kaise',
    'بہت': 'bahut', 'تگڑا': 'tagda', 'ہیٹس': 'hits', 'لویسی': 'Lucia', 'بے': 'bhai', 'سائیے': 'scene',
    'والا': 'wala', 'والی': 'wali', 'والے': 'wale', 'بات': 'baat', 'چیز': 'cheez', 'چیزیں': 'cheezein',
    'گیم': 'game', 'گاڑی': 'gaadi', 'گھر': 'ghar', 'لوگ': 'log', 'پورا': 'poora', 'ہاتھ': 'haath',
    'دوسری': 'doosri', 'دوسرا': 'doosra', 'بار': 'baar', 'زیادہ': 'zyada', 'زادہ': 'zyada',
    'صرف': 'sirf', 'ساتھ': 'saath', 'کچھ': 'kuch', 'کام': 'kaam', 'ٹائم': 'time', 'دن': 'din',
    'سال': 'saal', 'پیسے': 'paise', 'دوست': 'dost', 'سب': 'sab', 'شروع': 'shuru', 'ختم': 'khatam',
    'سچ': 'sach', 'جھوٹ': 'jhoot', 'اصلی': 'asli', 'نقلی': 'naqli', 'بڑا': 'bada', 'چھوٹا': 'chhota',
    'اسے': 'isse', 'اسکا': 'iska', 'اسکی': 'iski', 'اسکے': 'iske', 'انکا': 'unka', 'انکی': 'unki', 'انکے': 'unke',
    'رکھنے': 'rakhne', 'رکھا': 'rakha', 'رکھو': 'rakho', 'چھ': 'chhe', 'لاکھ': 'lakh',
    'اینیمیشنز': 'animations', 'اینیمیشن': 'animation', 'ٹیم': 'team', 'کرمنل': 'criminal',
    'پولیس': 'police', 'کار': 'car', 'ویپنز': 'weapons', 'ویپن': 'weapon', 'سٹوری': 'story',
    'چاہو': 'chaho', 'رہنا': 'rahna', 'ہوٹل': 'hotel', 'کپڑے': 'kapde', 'بدل': 'badal',
    'بندوق': 'bandook', 'بندوقیں': 'bandookein', 'گن': 'gun', 'فائر': 'fire', 'شاٹ': 'shot',
    'بھولا': 'bhola', 'پائیں': 'paayein', 'کھلوش': 'clothes', 'رینٹ': 'rent', 'رہ': 'rah',
    'پھیں': 'bhai', 'سائڈ': 'side', 'پوائنٹ': 'point', 'ویڈیو': 'video', 'کلپ': 'clip',
    'شیر': 'share', 'لائک': 'like', 'سبسکرائب': 'subscribe', 'کمنٹ': 'comment', 'کھلاڑی': 'player',
    'کھیل': 'khel', 'کھیلو': 'khelo', 'جیت': 'jeet', 'ہار': 'haar', 'لیول': 'level', 'مشن': 'mission',
    'گاڑیاں': 'gaadiyan', 'مست': 'mast', 'اوپی': 'OP', 'سین': 'scene', 'کلچ': 'clutch', 'ہیڈ': 'head',
    'بوٹ': 'bot', 'پرو': 'pro', 'نووب': 'noob'
}

URDU_CHARS = {
    'آ': 'aa', 'ا': 'a', 'ب': 'b', 'پ': 'p', 'ت': 't', 'ٹ': 't', 'ث': 's',
    'ج': 'j', 'چ': 'ch', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ڈ': 'd', 'ذ': 'z',
    'ر': 'r', 'ڑ': 'r', 'ز': 'z', 'ژ': 'zh', 'س': 's', 'ش': 'sh', 'ص': 's',
    'ض': 'z', 'ط': 't', 'ظ': 'z', 'ع': 'a', 'غ': 'gh', 'ف': 'f', 'ق': 'q',
    'ک': 'k', 'گ': 'g', 'ل': 'l', 'م': 'm', 'ن': 'n', 'ں': 'n', 'و': 'o',
    'ہ': 'h', 'ھ': 'h', 'ء': '', 'ی': 'i', 'ے': 'e', 'ۂ': 'h', 'ۃ': 't',
    '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4', '۵': '5', '۶': '6',
    '۷': '7', '۸': '8', '۹': '9'
}

URDU_SUPPRESS_TOKEN_IDS = [
    995, 1211, 1829, 1863, 1975, 2288, 2304, 2407, 2423, 2655, 3215, 3224, 3555, 3615, 3660, 3714, 3794, 4032, 4117, 4135,
    4587, 4724, 5016, 5172, 5296, 5551, 5718, 6007, 6024, 6027, 6055, 6156, 6225, 6354, 6808, 7251, 7369, 7435, 7565, 7578,
    7649, 8032, 8315, 8592, 8608, 8717, 8848, 8978, 9122, 9154, 9307, 9381, 9566, 9640, 9673, 9778, 9957, 10632, 10721, 10859,
    10874, 10943, 11082, 11203, 11242, 11296, 11331, 11536, 11616, 11622, 11703, 11778, 11933, 12138, 12174, 12399, 12602, 12610,
    12984, 13063, 13412, 13546, 13672, 14111, 14268, 14407, 14739, 14768, 14851, 15040, 15042, 15730, 15844, 16070, 16095, 16247,
    16254, 16373, 16472, 16490, 16572, 16606, 16712, 16758, 16761, 17082, 17195, 18513, 18863, 18871, 19446, 19452, 19528, 19753,
    19913, 19986, 20193, 20292, 20328, 20449, 20498, 20666, 21035, 21136, 21292, 21453, 21542, 21984, 22488, 22653, 22807, 23032,
    23180, 23275, 23328, 23557, 23758, 23905, 23942, 24049, 24061, 24192, 24401, 24525, 24621, 24637, 24793, 24976, 25062, 25124,
    25429, 25513, 25528, 25708, 25720, 25724, 25894, 25957, 25961, 26108, 26890, 26895, 27188, 27779, 27842, 27875, 27884, 28239,
    28242, 28259, 28480, 28543, 28671, 28697, 28814, 28820, 29245, 29325, 29399, 29538, 29688, 29739, 29910, 29973, 30241, 30543,
    30544, 30731, 30767, 31320, 31371, 31377, 31439, 31561, 31747, 31767, 31845, 32151, 32239, 32277, 32545, 32640, 32748, 32767,
    32771, 32887, 32930, 33251, 33427, 33456, 33491, 33546, 33599, 33604, 33608, 33688, 33753, 33911, 33962, 34051, 34105, 34190,
    34268, 34683, 34740, 34766, 34892, 35186, 35324, 35457, 35473, 35525, 35571, 36078, 36081, 36145, 36150, 36178, 36520, 36632,
    36725, 36764, 37037, 37130, 37279, 37440, 37495, 37746, 37893, 37977, 37983, 38149, 38207, 38251, 38392, 38436, 38637, 38688,
    38849, 38904, 39182, 39184, 39237, 39319, 39627, 39648, 39893, 39894, 39896, 40228, 40294, 40448, 41122, 41185, 41193, 41260,
    41361, 41779, 41850, 41891, 41924, 41950, 42213, 42903, 42963, 43020, 43042, 43242, 43500, 43527, 43596, 43761, 43947, 44049,
    44291, 44381, 44510, 44650, 44713, 44823, 44945, 45030, 45164, 45340, 45367, 45509, 45520, 45595, 45636, 45761, 45865, 46007,
    46152, 46201, 46309, 46456, 46538, 46599, 46740, 46811, 46952, 46958, 47283, 47302, 47341, 47356, 47395, 47416, 47432, 47524,
    47525, 47735, 48127, 48478, 48506, 48812, 48923, 49115, 49374, 49401, 49429, 49610, 49628, 49975, 50113, 50194, 50239
]

def get_urdu_suppress_tokens(model=None) -> List[int]:
    """
    Returns all 347 token IDs in Whisper tokenizer vocabulary that contain Arabic or Urdu script.
    Instantly returns precomputed set. Physically bars Whisper from decoding Urdu characters.
    """
    return list(URDU_SUPPRESS_TOKEN_IDS)

def detect_voice_language(model, wav_path: Union[str, Path]) -> Tuple[str, float]:
    """
    Recognizes the spoken language from the video's audio using Whisper voice detection.
    Strictly enforces:
    - If speaker is speaking English ('en' with high confidence): returns ('english', prob)
    - If speaker is speaking Hindi, Hinglish, or detected as Urdu ('hi', 'ur', 'pa', etc.):
      URDU IS COMPLETELY ELIMINATED and recognized as 'hinglish' (Roman Hindi)!
      returns ('hinglish', prob)
    """
    try:
        # Transcribe first few seconds or probe info
        _, info = model.transcribe(str(wav_path), beam_size=1)
        raw_lang = (info.language or "").lower()
        prob = float(info.language_probability or 0.0)

        if raw_lang == "en" and prob > 0.5:
            return "english", prob
        else:
            # All Hindi, Urdu, Punjabi, etc. are recognized as natural Hinglish
            return "hinglish", prob
    except Exception:
        return "hinglish", 1.0

def has_arabic_or_urdu(text: str) -> bool:
    """Checks if text contains Arabic or Urdu script characters."""
    if not text or not isinstance(text, str):
        return False
    return any(0x0600 <= ord(c) <= 0x06FF or 0x0750 <= ord(c) <= 0x077F or 0xFB50 <= ord(c) <= 0xFDFF or 0xFE70 <= ord(c) <= 0xFEFF for c in text)

def clean_urdu_word(w: str) -> str:
    # Strip surrounding punctuation for lookup
    m = re.match(r'^([^\w\s]*)([\w\s]+?)([^\w\s]*)$', w)
    if m:
        prefix, core, suffix = m.groups()
    else:
        prefix, core, suffix = '', w, ''

    if core in URDU_WORD_MAP:
        translated = URDU_WORD_MAP[core]
    else:
        translated = ''.join(URDU_CHARS.get(c, c) for c in core if not (0x0600 <= ord(c) <= 0x06FF and c not in URDU_CHARS))

    return f"{prefix}{translated}{suffix}"

def sanitize_urdu_to_hinglish(text: str) -> str:
    """Converts any Arabic/Urdu words or script directly into natural Roman Hinglish."""
    if not text or not isinstance(text, str) or not has_arabic_or_urdu(text):
        return text
    tokens = text.split()
    converted = [clean_urdu_word(t) for t in tokens]
    out = ' '.join(converted)
    # Remove any leftover untranslated arabic codepoints
    out = re.sub(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]', '', out)
    return re.sub(r'\s+', ' ', out).strip()

def sanitize_metadata_obj(obj: Any) -> Any:
    """Recursively converts all Urdu strings in dictionaries/lists to clean Roman Hinglish."""
    if isinstance(obj, str):
        return sanitize_urdu_to_hinglish(obj)
    elif isinstance(obj, list):
        return [sanitize_metadata_obj(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: sanitize_metadata_obj(v) for k, v in obj.items()}
    return obj

def sanitize_transcript_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sanitizes text and word arrays across Whisper transcript segments."""
    for s in segments:
        if "text" in s and has_arabic_or_urdu(s["text"]):
            s["text"] = sanitize_urdu_to_hinglish(s["text"])
        if "words" in s and s["words"]:
            for w in s["words"]:
                raw_w = w.get("word") or w.get("w", "")
                if has_arabic_or_urdu(raw_w):
                    clean_w = sanitize_urdu_to_hinglish(raw_w)
                    if "word" in w:
                        w["word"] = clean_w
                    if "w" in w:
                        w["w"] = clean_w
    return segments

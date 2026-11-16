import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.pipeline import snap_to_sentence_boundary

def test_sentence_snapping():
    # Simulated Whisper segments
    segments = [
        {"start": 10.0, "end": 14.5, "text": "Yeh pehla sentence hai."},
        {"start": 15.0, "end": 22.4, "text": "Yeh dusra bohot exciting part hai."},
        {"start": 23.0, "end": 35.8, "text": "Aur yahan aakar clip ka punchline khatam hota hai."}
    ]

    # Target raw start = 14.8, raw end = 35.2
    snapped_start, snapped_end = snap_to_sentence_boundary(segments, 14.8, 35.2)

    assert snapped_start == 15.0, f"Expected snapped start 15.0, got {snapped_start}"
    assert snapped_end == 35.8, f"Expected snapped end 35.8, got {snapped_end}"
    assert snapped_end - snapped_start >= 15.0, "Duration should be at least 15s"
    print("PASS: test_sentence_snapping")

if __name__ == "__main__":
    test_sentence_snapping()

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.subtitle_engine import format_ass_time, generate_hormozi_ass

def test_ass_time_formatting():
    assert format_ass_time(0.0) == "0:00:00.00"
    assert format_ass_time(65.25) == "0:01:05.25"
    assert format_ass_time(3661.50) == "1:01:01.50"
    print("PASS: format_ass_time")

def test_hormozi_ass_generation(tmp_path=None):
    if not tmp_path:
        tmp_path = Path(__file__).resolve().parent / "temp_test.ass"

    words = [
        {"word": "SCHOOL", "start": 0.5, "end": 0.9},
        {"word": "DANCE", "start": 0.95, "end": 1.4},
        {"word": "SCAM", "start": 1.45, "end": 2.1}
    ]

    out_file = generate_hormozi_ass(words, tmp_path, style_key="hormozi", position="bottom")
    assert out_file.exists(), "ASS file should be created"
    content = out_file.read_text(encoding="utf-8")
    assert "[Script Info]" in content
    assert "TrendingCaptions" in content
    assert "Dialogue:" in content
    assert r"{\c&H0000FFFF&\fscx118\fscy118}SCHOOL" in content
    # Verify auto-fit font size tag is present
    assert r"{\fs" in content
    out_file.unlink(missing_ok=True)
    print("PASS: generate_hormozi_ass (Phone Safe & Auto-Fit)")

if __name__ == "__main__":
    test_ass_time_formatting()
    test_hormozi_ass_generation()

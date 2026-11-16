import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.gemini_engine import clean_json_text
import json

def test_json_cleaner():
    raw_md = """```json
[
  {
    "title": "School Dance Exposed!",
    "viral_score": 98
  }
]
```"""
    cleaned = clean_json_text(raw_md)
    parsed = json.loads(cleaned)
    assert isinstance(parsed, list)
    assert parsed[0]["title"] == "School Dance Exposed!"
    assert parsed[0]["viral_score"] == 98
    print("PASS: test_json_cleaner")

if __name__ == "__main__":
    test_json_cleaner()

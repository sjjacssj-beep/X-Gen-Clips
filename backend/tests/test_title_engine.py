import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import title_desc_engine

def test_garbled_titles_transformation():
    test_samples = [
        ("Get it is that money is #shorts", "Bank Heist Money Glitch", "GTA 6"),
        ("Get the pills wait I forgot", "Hospital Escape Mission", "GTA 6"),
        ("I got a piece so bad", "Secret Weapon Gunfight", "GTA 6"),
        ("Oh shit I gotta go get", "5-Star Police Chase", "GTA 6"),
        ("Jason I know you and I", "Story Leaked Cutscene", "GTA 6")
    ]

    print("\n=== GARBLED TITLES TRANSFORMATION TEST ===")
    for old, theme, topic in test_samples:
        titles = title_desc_engine.generate_3_titles(
            primary_topic=topic,
            clip_theme=theme,
            mood="shock_action",
            language="hinglish",
            emoji_level="low"
        )
        print(f"\n[BEFORE]: {old}")
        assert len(titles) == 3
        emojis_used = set()
        for t in titles:
            title_text = t["title"]
            is_valid, reason = title_desc_engine.validate_title(
                title=title_text,
                topic_keywords=[topic, "GTA"],
                max_chars=60,
                allowed_lang="hinglish"
            )
            print(f"  -> [{t['angle']}]: {title_text} (Length: {len(title_text)}, Valid: {is_valid})")
            assert is_valid, f"Title invalid: {reason}"
            assert len(title_text) <= 60
            assert topic.lower() in title_text.lower()
            if t["emoji"]:
                emojis_used.add(t["emoji"])
        
        # Verify all 3 titles have distinct emojis
        assert len(emojis_used) == 3, f"Expected 3 distinct emojis, got {emojis_used}"

    # Test 4-line description generator
    descs = title_desc_engine.generate_2_descriptions(
        primary_topic="GTA 6",
        clip_summary="Jason aur Lucia ne police ko chakra kar escape kiya",
        hashtags=["#GTA6", "#Gaming", "#ViceCity"],
        language="hinglish",
        emoji_level="low"
    )
    assert len(descs) == 2
    for d in descs:
        lines = d["lines"]
        assert len(lines) == 4
        print(f"\n[DESCRIPTION {d['id']} - {d['label']}]:\n{d['text']}")

    print("\n✓ ALL TITLE & DESCRIPTION ENGINE TESTS PASSED!")

if __name__ == "__main__":
    test_garbled_titles_transformation()

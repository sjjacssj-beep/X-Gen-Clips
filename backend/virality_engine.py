import logging
import re
from typing import Dict, Any, List, Optional

logger = logging.getLogger("xgenclips.virality")

class BaseViralityAdapter:
    """Pluggable adapter interface for external scorers (e.g. vidIQ, TubeBuddy)."""
    def __init__(self, name: str, enabled: bool = False):
        self.name = name
        self.enabled = enabled

    def score_title_keywords(self, title: str, keywords: List[str]) -> Dict[str, Any]:
        """Override to query third-party ranking APIs."""
        return {"adapter": self.name, "score": 85, "suggestions": []}

class ProprietaryViralityEngine:
    def __init__(self):
        self.adapters: List[BaseViralityAdapter] = []

    def compute_virality_score(
        self,
        hook_text: str,
        spoken_text: str,
        duration_sec: float,
        audio_energy_score: float = 75.0,
        words_per_minute: float = 145.0
    ) -> Dict[str, Any]:
        """
        Computes 5-dimension viral score (0 - 100):
        1. Hook Strength (0 - 30 pts): first 3-sec curiosity gap
        2. Emotional Peak (0 - 25 pts): audio energy + punctuation
        3. Narrative Completeness (0 - 20 pts): self-contained payoff
        4. Pacing & Flow (0 - 15 pts): optimal WPM (130 - 170)
        5. Length Fit (0 - 10 pts): optimal retention bracket (25 - 45s)
        """
        # 1. Hook Strength (0 - 30)
        hook_pts = 15.0
        h_upper = hook_text.upper()
        if any(w in h_upper for w in ("WAIT", "WATCH", "NEVER", "OMG", "SECRET", "TWIST", "SACH", "CLUTCH")):
            hook_pts += 10.0
        if any(char in hook_text for char in ("?", "!")):
            hook_pts += 5.0
        hook_pts = min(30.0, hook_pts)

        # 2. Emotional Peak (0 - 25)
        emo_pts = min(25.0, (audio_energy_score / 100.0) * 20.0 + (spoken_text.count("!") * 2.5))

        # 3. Completeness (0 - 20)
        # Check if ends with punctuation and doesn't trail off with "and", "or", "so"
        words = spoken_text.strip().split()
        completeness_pts = 16.0
        if words and words[-1].lower() in ("and", "or", "so", "but", "kyunki"):
            completeness_pts -= 8.0
        if spoken_text.endswith((".", "!", "?")):
            completeness_pts += 4.0
        completeness_pts = max(5.0, min(20.0, completeness_pts))

        # 4. Pacing & Flow (0 - 15)
        # Optimal Shorts WPM is 140 - 170
        pacing_pts = max(5.0, 15.0 - abs(155.0 - words_per_minute) * 0.25)

        # 5. Length Fit (0 - 10)
        # 25 - 45s has the highest completion rate on YouTube Shorts
        if 25.0 <= duration_sec <= 45.0:
            length_pts = 10.0
        elif 15.0 <= duration_sec <= 60.0:
            length_pts = 8.0
        else:
            length_pts = 5.0

        total = round(hook_pts + emo_pts + completeness_pts + pacing_pts + length_pts)
        total = max(45, min(99, total))

        # Generate 1-line reason & actionable improvement tip
        if total >= 88:
            tier = "Tier A (Viral Gold)"
            reason = "High 3-second hook curiosity paired with explosive audio climax creates peak retention."
            improvement = "Thumbnail text me spoken line se alag curiosity word lagayein."
        elif total >= 72:
            tier = "Tier B (High Retention)"
            reason = "Strong pacing and good emotional momentum; narrative payoff delivers clearly."
            improvement = "Pehle 2 second me punch zoom thoda aggressive karein taaki swipe-away 0 ho."
        else:
            tier = "Tier C (Contextual)"
            reason = "Moderate pacing; narrative thoda slow start ho raha hai."
            improvement = "Starting dead-air ko cut karein aur title me specific number/curiosity hook add karein."

        return {
            "score": total,
            "tier": tier,
            "breakdown": {
                "hook_strength": round(hook_pts, 1),
                "emotional_peak": round(emo_pts, 1),
                "completeness": round(completeness_pts, 1),
                "pacing": round(pacing_pts, 1),
                "length_fit": round(length_pts, 1)
            },
            "reason": reason,
            "improvement_tip": improvement
        }

virality_engine = ProprietaryViralityEngine()

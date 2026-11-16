"""Sound labels: map the audio model's names to our canonical ones, and questions to groups of labels.

Matching is by KEYWORD, not exact AudioSet names, so a spelling difference in the model's label list can't silently
disable detection. At model load the tagger also checks which canonical labels are reachable (see `reachable`).
"""
from __future__ import annotations

# canonical labels we store
BABY_CRY, CRYING, WHIMPER = "baby_cry", "crying", "whimper"
BABY_LAUGH, GIGGLE, LAUGHTER = "baby_laugh", "giggle", "laughter"
BABY_BABBLE, CHILD_SPEECH = "baby_babble", "child_speech"

ALL_LABELS = (BABY_CRY, CRYING, WHIMPER, BABY_LAUGH, GIGGLE, LAUGHTER, BABY_BABBLE, CHILD_SPEECH)

# what a question's sound matches (canonical labels, any one counts)
GROUPS: dict[str, tuple[str, ...]] = {
    "baby_cry": (BABY_CRY, CRYING, WHIMPER),
    "baby_laugh": (BABY_LAUGH, GIGGLE, LAUGHTER),
    "baby_coo": (BABY_BABBLE,),
}


def canonical_label(model_label: str) -> str | None:
    """'Baby cry, infant cry' -> baby_cry; 'Giggle' -> giggle; unrelated labels -> None."""
    t = model_label.lower()
    if "baby" in t or "infant" in t:
        if "cry" in t:
            return BABY_CRY
        if "laugh" in t:
            return BABY_LAUGH
    if "babbl" in t:
        return BABY_BABBLE
    if "giggl" in t or "chuckl" in t:
        return GIGGLE
    if "laugh" in t:
        return LAUGHTER
    if "whimper" in t:
        return WHIMPER
    if "cry" in t or "sobb" in t:
        return CRYING
    if "child speech" in t or "kid speaking" in t:
        return CHILD_SPEECH
    return None


def group_for(sound: str) -> tuple[str, ...] | None:
    """Turn the question parser's free-form sound ('baby_laughing', 'cry', 'giggling') into labels to search for."""
    t = sound.lower().replace("-", "_")
    if any(k in t for k in ("cry", "cried", "sob", "whimper", "wail")):
        return GROUPS["baby_cry"]
    if any(k in t for k in ("laugh", "giggl", "chuckl")):  # stems: 'giggling' doesn't contain 'giggle'
        return GROUPS["baby_laugh"]
    if any(k in t for k in ("coo", "babbl")):
        return GROUPS["baby_coo"]
    return None


def reachable(model_labels) -> set[str]:
    """Which canonical labels the loaded model can actually produce."""
    return {c for c in (canonical_label(l) for l in model_labels) if c}

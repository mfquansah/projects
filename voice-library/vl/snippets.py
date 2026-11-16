"""Pick the moment in a transcript that best matches a search, so a result can show it and jump to its timestamp."""
from __future__ import annotations

import re

STOP = {
    "the", "and", "for", "that", "this", "with", "about", "from", "have", "was", "were", "are", "you", "your", "what", "when",
    "where", "which", "who", "how", "why", "can", "could", "would", "should", "not", "but", "all", "any", "has", "had", "its",
    "into", "than", "then", "them", "they", "there", "their", "just", "like", "get", "got", "one", "some", "my", "me", "of",
    "recording", "recordings", "note", "notes", "voice", "find", "show", "idea", "thing", "about",
    "looking", "look", "audio", "sound", "sounds", "hear", "heard", "listen", "clip", "clips", "file", "files", "want", "need",
}


def query_terms(*texts: str) -> list[str]:
    """Meaningful words from the query (and any keywords the question parser found), in order, no duplicates."""
    seen, out = set(), []
    for text in texts:
        for w in re.findall(r"[A-Za-z0-9']+", (text or "").lower()):
            w = w.strip("'")
            if len(w) >= 3 and w not in STOP and w not in seen:
                seen.add(w)
                out.append(w)
    return out


def _pattern(terms: list[str]):
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + r")\w*", re.I)


def best_snippet(segments: list[dict], full_text: str, terms: list[str], max_chars: int = 170) -> dict | None:
    """{'t': seconds or None, 'parts': [{'t': text, 'm': is_match}]} for the segment matching the most distinct terms.

    Returns None when nothing matches (so a result found only by meaning or by sound shows no fake highlight).
    """
    if not terms:
        return None
    rx = _pattern(terms)
    cands = [(float(s.get("start", 0)), str(s.get("text", ""))) for s in segments if s.get("text")]
    if not cands and full_text.strip():
        cands = [(None, full_text.strip())]
    best, best_score = None, 0
    for start, text in cands:
        score = len({m.group(0).lower()[:len(t)] for m in rx.finditer(text) for t in terms if m.group(0).lower().startswith(t)})
        if score > best_score:
            best, best_score = (start, text), score
    if best is None:
        return None
    start, text = best
    first = rx.search(text)
    lo, hi, pre, post = 0, len(text), "", ""
    if len(text) > max_chars:
        lo = max(0, first.start() - 60)
        hi = min(len(text), lo + max_chars)
        pre, post = ("…" if lo > 0 else ""), ("…" if hi < len(text) else "")
    window = text[lo:hi].strip()
    parts, pos = [], 0
    for m in rx.finditer(window):
        if m.start() > pos:
            parts.append({"t": window[pos:m.start()], "m": False})
        parts.append({"t": m.group(0), "m": True})
        pos = m.end()
    if pos < len(window):
        parts.append({"t": window[pos:], "m": False})
    if pre:
        parts.insert(0, {"t": pre, "m": False})
    if post:
        parts.append({"t": post, "m": False})
    return {"t": start, "parts": parts}

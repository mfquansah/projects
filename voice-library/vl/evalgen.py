"""Generate an eval question set from the library itself, for when you can't remember what you recorded.

Three sources, none needing your memory:
 1. content  - an LLM reads each note and writes questions someone might ask to find it (answer = that note).
 2. property/date - answers computed from the library's own data (longest, newest, a busy month).
 3. none     - topics checked to appear in NONE of your transcripts, so "nothing" is the right answer.

Caveat: LLM-written questions echo the note's own content, so scores run optimistic. The writer is told to
paraphrase and avoid distinctive names, but treat this as a smoke test, not a gold standard.
"""
from __future__ import annotations

import calendar
import json
import re
from collections import Counter
from typing import Callable, Protocol

from sqlalchemy.orm import Session

from vl.db import Enrichment, Note, Transcript

# Generic topics unlikely to be in anyone's notes; kept ONLY if absent from every transcript.
ABSENT_CANDIDATES = [
    ("my favourite pizza topping", ["pizza", "topping"]),
    ("booking a flight to Tokyo", ["tokyo", "flight"]),
    ("guitar lesson with my teacher", ["guitar"]),
    ("filing my tax return", ["tax return", "taxes"]),
    ("the vet appointment for the dog", ["vet", "veterinar"]),
    ("our wedding anniversary dinner", ["anniversary", "wedding"]),
]


class QuestionWriter(Protocol):
    def write(self, title: str, summary: str, transcript: str, n: int) -> list[str]: ...


WRITER_PROMPT = """Someone is searching their personal voice-note library and only vaguely remembers this note.
Write {n} different questions they might type to find it. Rules: paraphrase, do not copy distinctive names or exact
phrases from the transcript; do not mention a filename; each question must fit THIS note and not be generic.
Reply with ONLY a JSON array of {n} strings.
Title: {title}
Summary: {summary}
Transcript (start): {transcript}"""


class ClaudeQuestionWriter:
    def __init__(self, model: str = "claude-haiku-5-5", client=None) -> None:
        if client is None:
            import anthropic  # lazy

            client = anthropic.Anthropic()
        self.model, self._client = model, client

    def write(self, title: str, summary: str, transcript: str, n: int) -> list[str]:
        msg = self._client.messages.create(
            model=self.model, max_tokens=400,
            messages=[{"role": "user", "content": WRITER_PROMPT.format(
                n=n, title=title, summary=summary, transcript=transcript[:1500])}])
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if not m:
            raise ValueError(f"no JSON array in reply: {' '.join(raw.split())[:120]!r}")
        return [str(q).strip() for q in json.loads(m.group(0)) if str(q).strip()][:n]


def content_questions(s: Session, writer: QuestionWriter, per_note: int = 2,
                      max_notes: int | None = None) -> tuple[list[dict], list[str]]:
    """One or more questions per enriched note. Failures on a note are reported, not fatal."""
    out, problems = [], []
    rows = (s.query(Note, Enrichment, Transcript)
            .join(Enrichment, Enrichment.note_id == Note.id)
            .join(Transcript, Transcript.note_id == Note.id).order_by(Note.id).all())
    for note, en, tr in rows[:max_notes]:
        if not tr.text.strip():
            problems.append(f"{note.original_name}: empty transcript, skipped")
            continue
        try:
            qs = writer.write(en.title, en.summary, tr.text, per_note)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{note.original_name}: {type(exc).__name__}: {exc}")
            continue
        for q in qs:
            out.append({"q": q, "kind": "content", "expect": [note.original_name],
                        "check": f"{en.title} | {en.summary}"})
    return out, problems


def property_questions(s: Session) -> tuple[list[dict], list[str]]:
    """Answers come from the library's data. They WILL fail until `ask` supports sorting; that's the point."""
    notes = s.query(Note).all()
    out, skipped = [], []
    timed = [n for n in notes if n.duration_s]
    if timed:
        out.append({"q": "my longest voice note", "kind": "property",
                    "expect": [max(timed, key=lambda n: n.duration_s).original_name]})
        out.append({"q": "my shortest voice note", "kind": "property",
                    "expect": [min(timed, key=lambda n: n.duration_s).original_name]})
    else:
        skipped.append("no durations recorded: skipped longest/shortest")
    dated = [n for n in notes if n.recorded_at]
    if dated:
        out.append({"q": "my most recent voice note", "kind": "property",
                    "expect": [max(dated, key=lambda n: n.recorded_at).original_name]})
        out.append({"q": "my oldest voice note", "kind": "property",
                    "expect": [min(dated, key=lambda n: n.recorded_at).original_name]})
        (ym, count), = Counter((n.recorded_at.year, n.recorded_at.month) for n in dated).most_common(1)
        names = [n.original_name for n in dated if (n.recorded_at.year, n.recorded_at.month) == ym]
        out.append({"q": f"voice notes from {calendar.month_name[ym[1]]} {ym[0]}", "kind": "date", "expect": names})
    else:
        skipped.append("no dates recorded: skipped date questions")
    return out, skipped


def absent_questions(s: Session) -> list[dict]:
    corpus = " ".join(t.text.lower() for t in s.query(Transcript)) + " " + \
             " ".join(f"{e.title} {e.summary}".lower() for e in s.query(Enrichment))
    return [{"q": q, "kind": "none", "expect": []}
            for q, words in ABSENT_CANDIDATES if not any(w in corpus for w in words)]


def review(questions: list[dict], ask_user: Callable[[str], str] = input,
           show: Callable[[str], None] = print) -> list[dict]:
    """Let the user keep (Enter/y), drop (n) or rewrite (type new text) each CONTENT question after seeing the note it came from."""
    kept = []
    content = [q for q in questions if q["kind"] == "content"]
    for i, q in enumerate(content, 1):
        show(f"\n[{i}/{len(content)}] Note: {q['check']}\n  Question: {q['q']}")
        ans = ask_user("  Enter/y = keep, n = drop, or type a better question: ").strip()
        if ans.lower() == "n":
            continue
        if ans and ans.lower() != "y":
            q = {**q, "q": ans}
        kept.append({**q, "reviewed": True})
    return kept + [q for q in questions if q["kind"] != "content"]

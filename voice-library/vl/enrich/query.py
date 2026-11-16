"""Natural-language query layer.

The LLM only TRANSLATES a question into structured filters and (optionally) explains/reranks results.
It never searches audio and never invents notes: every result still comes from the database.
Only the question text and a few short transcript snippets are sent to the API; audio never is.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class StructuredQuery:
    semantic_text: str  # what the note is about, for search by meaning
    keywords: list[str] = field(default_factory=list)  # words likely spoken, for keyword search
    category: str | None = None
    since: dt.datetime | None = None
    until: dt.datetime | None = None  # exclusive
    sort: str | None = None  # longest | shortest | newest | oldest
    count: int | None = None  # "my 3 longest notes" -> 3
    sound: str | None = None  # e.g. "baby_laugh"; recorded but NOT applied until sound tagging exists (milestone 2)
    notes: list[str] = field(default_factory=list)  # things to tell the user (ignored/invalid parts)


class QueryParser(Protocol):
    def parse(self, question: str, categories: list[str], today: dt.date) -> StructuredQuery: ...


class Reranker(Protocol):
    def rerank(self, question: str, candidates: list[dict]) -> list[dict]:
        """candidates: [{id, title, summary, snippet}] -> ordered [{id, why}] (may drop weak matches)."""


PARSE_PROMPT = """You translate a question about someone's personal voice-note library into a search query.
Today is {today}. Reply with ONLY a JSON object:
{{"semantic_text": "short description of what the note is about, or empty string if the question is only about a property like length or date",
"keywords": ["words likely spoken in the note, lowercase, at most 6"],
"category": "<one of: {categories}> or null (only if the question clearly implies one)",
"since": "YYYY-MM-DD or null", "until": "YYYY-MM-DD or null (exclusive end)",
"sound": "baby_cry | baby_laugh | baby_coo | other sound label | null",
"sort": "longest | shortest | newest | oldest | null (only if the question asks for an ordering or extreme)",
"count": <integer if the question asks for a number of notes, e.g. "my 3 longest", else null>}}
Sound rules: set "sound" whenever the question is about how something SOUNDS, not only what is said. Baby/child sounds,
noises, cooing, babbling, gurgling, "cute sounds" -> baby_coo. Crying, fussing, wailing -> baby_cry. Laughing, giggling -> baby_laugh.
Rules: convert relative dates ("two weeks ago", "last summer", "two years ago") into a date RANGE using today's date;
be generous with vague phrases (a week-long range for "about two weeks ago"). Leave a field null when the question
doesn't say. Do not invent details.
Question: {question}"""

RERANK_PROMPT = """A user asked: "{question}"
Below are candidate voice notes. Reply with ONLY a JSON array, best match first, of
{{"id": <id>, "why": "one short sentence on why it matches"}}. Omit candidates that clearly do not match.
Candidates:
{candidates}"""


def _json(raw: str, opener: str, closer: str):
    m = re.search(re.escape(opener) + r".*" + re.escape(closer), raw, re.DOTALL)
    if not m:
        raise ValueError("no JSON in model reply")
    return json.loads(m.group(0))


def _date(value, label: str, notes: list[str]) -> dt.datetime | None:
    if not value or value == "null":
        return None
    try:
        return dt.datetime.fromisoformat(str(value))
    except ValueError:
        notes.append(f"Ignored an unreadable {label} date from the model: {value!r}")
        return None


def parse_structured(raw: str, question: str, categories: list[str]) -> StructuredQuery:
    data = _json(raw, "{", "}")
    notes: list[str] = []
    since = _date(data.get("since"), "start", notes)
    until = _date(data.get("until"), "end", notes)
    if since and until and until <= since:
        notes.append("Ignored the date range because it ended before it started.")
        since = until = None
    category = data.get("category")
    if category in (None, "", "null"):
        category = None
    elif category not in categories:
        notes.append(f"Ignored unknown category {category!r}.")
        category = None
    sound = data.get("sound")
    sound = None if sound in (None, "", "null") else str(sound)
    sort = data.get("sort")
    sort = str(sort).lower() if sort not in (None, "", "null") else None
    if sort not in (None, "longest", "shortest", "newest", "oldest"):
        notes.append(f"Ignored unknown sort {sort!r}.")
        sort = None
    count = data.get("count")
    try:
        count = int(count) if count not in (None, "", "null") else None
    except (TypeError, ValueError):
        count = None
    if count is not None and not 1 <= count <= 50:
        count = None
    topic = str(data.get("semantic_text") or "").strip()
    if not topic and not sort:
        topic = question  # no sort and no topic from the model: fall back to the raw question
    return StructuredQuery(
        semantic_text=topic, sort=sort, count=count,
        keywords=[str(k).lower() for k in data.get("keywords", []) if str(k).strip()][:6],
        category=category, since=since, until=until, sound=sound, notes=notes,
    )


class ClaudeQueryParser:
    def __init__(self, model: str = "claude-haiku-5-5") -> None:
        import anthropic  # lazy

        self.model = model
        self._client = anthropic.Anthropic()

    def parse(self, question: str, categories: list[str], today: dt.date) -> StructuredQuery:
        msg = self._client.messages.create(
            model=self.model, max_tokens=400,
            messages=[{"role": "user", "content": PARSE_PROMPT.format(
                today=today.isoformat(), categories=", ".join(categories), question=question)}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return parse_structured(raw, question, categories)


def parse_rerank(raw: str, valid_ids: set[int]) -> list[dict]:
    items = _json(raw, "[", "]")
    out, seen = [], set()
    for it in items:
        try:
            nid = int(it["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if nid in valid_ids and nid not in seen:  # ignore ids the model made up
            seen.add(nid)
            out.append({"id": nid, "why": str(it.get("why", "")).strip()})
    return out


class ClaudeReranker:
    def __init__(self, model: str = "claude-haiku-5-5") -> None:
        import anthropic  # lazy

        self.model = model
        self._client = anthropic.Anthropic()

    def rerank(self, question: str, candidates: list[dict]) -> list[dict]:
        listing = "\n".join(
            f'- id {c["id"]}: "{c["title"]}" | {c["summary"]} | transcript start: {c["snippet"]}' for c in candidates)
        msg = self._client.messages.create(
            model=self.model, max_tokens=800,
            messages=[{"role": "user", "content": RERANK_PROMPT.format(question=question, candidates=listing)}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return parse_rerank(raw, {c["id"] for c in candidates})

"""LLM enrichment: title, summary, category, tags, purpose, junk score.

Only transcript TEXT is sent to the API, never audio. The pipeline depends on the Enricher protocol, so tests use a fake.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class EnrichmentResult:
    title: str
    summary: str
    category: str  # must be one of the offered categories, else "Other"
    suggested_category: str | None = None  # a NEW category the user may accept; never applied automatically
    purpose: str = ""
    tags: list[str] = field(default_factory=list)
    junk_score: float = 0.0  # 0 = clearly worth keeping, 1 = likely accidental/empty
    model_version: str = ""


class Enricher(Protocol):
    model_version: str

    def enrich(self, transcript: str, categories: list[str], recorded_at: str | None) -> EnrichmentResult: ...


PROMPT = """You organize a person's personal voice notes. Read the transcript and reply with ONLY a JSON object:
{{"title": "<=8 words", "summary": "1-2 sentences", "category": "<one of: {categories}>",
"suggested_category": "<a new category name if none fit well, else null>",
"purpose": "short phrase, e.g. idea / reminder / family moment / meeting recap / venting",
"tags": ["3-6 lowercase tags"], "junk_score": <0 to 1, high if empty, accidental or unintelligible>}}
Recorded: {recorded_at}
Transcript:
{transcript}"""


def parse_enrichment(raw: str, categories: list[str], model_version: str) -> EnrichmentResult:
    """Tolerant JSON parsing: models sometimes wrap JSON in prose or code fences."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in model reply")
    data = json.loads(match.group(0))
    category = data.get("category") or "Other"
    if category not in categories:
        category = "Other"
    suggested = data.get("suggested_category")
    if suggested in (None, "", "null") or suggested in categories:
        suggested = None
    try:
        junk = min(1.0, max(0.0, float(data.get("junk_score", 0))))
    except (TypeError, ValueError):
        junk = 0.0
    return EnrichmentResult(
        title=str(data.get("title", "")).strip() or "Untitled note",
        summary=str(data.get("summary", "")).strip(),
        category=category,
        suggested_category=suggested,
        purpose=str(data.get("purpose", "")).strip(),
        tags=[str(t).strip().lower() for t in data.get("tags", []) if str(t).strip()][:8],
        junk_score=junk,
        model_version=model_version,
    )


class ClaudeEnricher:
    """Uses the Anthropic API. Needs `pip install anthropic` and ANTHROPIC_API_KEY."""

    def __init__(self, model: str = "claude-haiku-5-5") -> None:
        import anthropic  # lazy

        self.model_version = model
        self._client = anthropic.Anthropic()

    def enrich(self, transcript: str, categories: list[str], recorded_at: str | None) -> EnrichmentResult:
        if not transcript.strip():
            return EnrichmentResult(
                title="Untitled note", summary="No speech detected.", category="Other",
                junk_score=0.7, model_version=self.model_version,
            )
        msg = self._client.messages.create(
            model=self.model_version,
            max_tokens=500,
            messages=[{"role": "user", "content": PROMPT.format(
                categories=", ".join(categories), recorded_at=recorded_at or "unknown",
                transcript=transcript[:12000])}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return parse_enrichment(raw, categories, self.model_version)

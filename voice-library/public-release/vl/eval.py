"""Evaluation harness: score search quality on a fixed list of questions, the same way every time.

questions.json:
  {"questions": [
     {"q": "the dashboard meeting", "kind": "content", "expect": ["Team meeting.m4a"]},
     {"q": "my favourite pizza topping", "kind": "none", "expect": []}
  ]}
- `expect`: original filenames (any one of them counts as correct). Must be non-empty, except for kind "none".
- kind "none": a topic that was never recorded. Correct = nothing returned (a hit is a false positive).
- other kinds are free-form labels used for the per-kind breakdown (content, date, property, ...).

Modes compared: `search` (local only), `ask-norerank` (Claude parses the question) and `ask` (parse + rerank).
Metrics: hit@1/3/5, MRR (mean reciprocal rank), "correctly empty" for kind none, seconds and LLM call counts.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from vl.db import Note
from vl.index.search import Hit

KS = (1, 3, 5)
Runner = Callable[[str], tuple[list[Hit], list[str]]]


class EvalSetError(ValueError):
    """The questions file is unusable; message says what to fix."""


@dataclass
class Question:
    q: str
    kind: str
    expect: list[str]


@dataclass
class QResult:
    q: str
    kind: str
    expect: list[str]
    rank: int | None  # 1-based position of the first expected note; None = not returned
    returned: list[str]  # top results (filenames)
    notes: list[str]
    seconds: float
    error: str | None = None

    @property
    def is_none(self) -> bool:
        return self.kind == "none"

    @property
    def correct_empty(self) -> bool:
        return self.is_none and not self.returned and not self.error


@dataclass
class ModeReport:
    mode: str
    results: list[QResult] = field(default_factory=list)
    llm_calls: int = 0

    def _scored(self) -> list[QResult]:
        return [r for r in self.results if not r.is_none]

    def hit_at(self, k: int) -> float | None:
        sc = self._scored()
        return sum(1 for r in sc if r.rank is not None and r.rank <= k) / len(sc) if sc else None

    def mrr(self) -> float | None:
        sc = self._scored()
        return sum(1.0 / r.rank for r in sc if r.rank) / len(sc) if sc else None

    def empty_score(self) -> tuple[int, int] | None:
        nones = [r for r in self.results if r.is_none]
        return (sum(r.correct_empty for r in nones), len(nones)) if nones else None

    def by_kind(self) -> dict[str, tuple[int, int]]:
        out: dict[str, list[int]] = {}
        for r in self._scored():
            a = out.setdefault(r.kind, [0, 0])
            a[1] += 1
            a[0] += 1 if r.rank == 1 else 0
        return {k: (v[0], v[1]) for k, v in out.items()}

    def summary(self) -> dict:
        secs = [r.seconds for r in self.results]
        return {
            "mode": self.mode,
            **{f"hit@{k}": self.hit_at(k) for k in KS},
            "mrr": self.mrr(),
            "correctly_empty": self.empty_score(),
            "errors": sum(1 for r in self.results if r.error),
            "avg_seconds": sum(secs) / len(secs) if secs else 0.0,
            "llm_calls": self.llm_calls,
        }


def load_questions(path: Path) -> list[Question]:
    try:
        data = json.loads(Path(path).read_text())
    except json.JSONDecodeError as exc:
        raise EvalSetError(f"{path} is not valid JSON: {exc}") from exc
    items = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise EvalSetError('Expected {"questions": [ ... ]} with at least one question.')
    out: list[Question] = []
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict) or not str(it.get("q", "")).strip():
            raise EvalSetError(f"Question #{i} needs a non-empty \"q\".")
        kind = str(it.get("kind", "content")).strip() or "content"
        expect = it.get("expect", [])
        if not isinstance(expect, list) or not all(isinstance(e, str) for e in expect):
            raise EvalSetError(f"Question #{i} ({it['q']!r}): \"expect\" must be a list of filenames.")
        if kind == "none" and expect:
            raise EvalSetError(f"Question #{i} ({it['q']!r}): kind \"none\" must have an empty \"expect\".")
        if kind != "none" and not expect:
            raise EvalSetError(f"Question #{i} ({it['q']!r}): needs at least one expected filename "
                               "(or set kind to \"none\" if nothing should match).")
        out.append(Question(q=it["q"].strip(), kind=kind, expect=expect))
    return out


def check_expected_exist(session: Session, questions: list[Question]) -> None:
    """A typo in `expect` would silently score as a miss, so fail loudly instead."""
    known = {n.original_name for n in session.query(Note.original_name)}
    folded = {k.lower() for k in known}
    problems = []
    for i, q in enumerate(questions, 1):
        for name in q.expect:
            if name.lower() not in folded:
                problems.append(f"  #{i} {q.q!r}: no imported note named {name!r}")
    if problems:
        raise EvalSetError("Expected filenames not found in the library:\n" + "\n".join(problems)
                           + "\nUse the exact names (see `python -m vl.cli status` or the notes table).")


def run_mode(session: Session, mode: str, runner: Runner, questions: list[Question], top_k: int = 5) -> ModeReport:
    rep = ModeReport(mode=mode)
    for q in questions:
        expected = {e.lower() for e in q.expect}
        t0 = time.perf_counter()
        try:
            hits, notes = runner(q.q)
            err = None
        except Exception as exc:  # noqa: BLE001 - one broken question must not end the run
            hits, notes, err = [], [], f"{type(exc).__name__}: {exc}"
        secs = time.perf_counter() - t0
        names = [session.get(Note, h.note_id).original_name for h in hits]
        rank = next((i for i, n in enumerate(names, 1) if n.lower() in expected), None)
        rep.results.append(QResult(q=q.q, kind=q.kind, expect=q.expect, rank=rank,
                                   returned=names[:top_k], notes=notes, seconds=secs, error=err))
    return rep


def pct(x: float | None) -> str:
    return "  n/a" if x is None else f"{x * 100:4.0f}%"


def format_report(reports: list[ModeReport]) -> str:
    lines = ["", f"{'mode':<14}{'hit@1':>7}{'hit@3':>7}{'hit@5':>7}{'MRR':>7}{'empty-ok':>10}{'errors':>8}{'avg s':>8}{'LLM calls':>11}"]
    for r in reports:
        s = r.summary()
        e = s["correctly_empty"]
        mrr = f"{s['mrr']:.2f}" if s["mrr"] is not None else "n/a"
        empty = f"{e[0]}/{e[1]}" if e else "n/a"
        lines.append(
            f"{s['mode']:<14}{pct(s['hit@1']):>7}{pct(s['hit@3']):>7}{pct(s['hit@5']):>7}"
            f"{mrr:>7}{empty:>10}{s['errors']:>8}{s['avg_seconds']:>8.1f}{s['llm_calls']:>11}")
    kinds = sorted({k for r in reports for k in r.by_kind()})
    if kinds:
        lines += ["", "Right note FIRST, by kind (correct/total):"]
        for k in kinds:
            cells = "  ".join(f"{r.mode}: {r.by_kind().get(k, (0, 0))[0]}/{r.by_kind().get(k, (0, 0))[1]}" for r in reports)
            lines.append(f"  {k:<10}{cells}")
    lines += ["", "Misses (expected note not in top results):"]
    any_miss = False
    for r in reports:
        for x in r.results:
            if x.error:
                lines.append(f"  [{r.mode}] ERROR on {x.q!r}: {x.error}")
                any_miss = True
            elif x.is_none and x.returned:
                lines.append(f"  [{r.mode}] FALSE POSITIVE on {x.q!r}: returned {x.returned[:3]}")
                any_miss = True
            elif not x.is_none and x.rank is None:
                lines.append(f"  [{r.mode}] MISS {x.q!r}: wanted {x.expect}, got {x.returned[:3] or 'nothing'}")
                any_miss = True
            elif not x.is_none and x.rank and x.rank > 1:
                lines.append(f"  [{r.mode}] LOW  {x.q!r}: right note at rank {x.rank}")
                any_miss = True
    if not any_miss:
        lines.append("  none")
    return "\n".join(lines)


def to_json(reports: list[ModeReport], question_file: str) -> str:
    return json.dumps({
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "question_file": question_file,
        "summary": [r.summary() for r in reports],
        "results": {r.mode: [asdict(x) for x in r.results] for r in reports},
    }, indent=2, default=str)


class Counting:
    """Wrap a parser/reranker to count how many LLM calls a mode made (a proxy for cost)."""

    def __init__(self, inner, method: str) -> None:
        self._inner, self._method, self.calls = inner, method, 0

    def __getattr__(self, name):
        if name != self._method:
            return getattr(self._inner, name)

        def call(*a, **kw):
            self.calls += 1
            return getattr(self._inner, name)(*a, **kw)
        return call

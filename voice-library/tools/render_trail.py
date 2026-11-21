#!/usr/bin/env python3
"""Render the build trail (docs/*.md) into one self-contained HTML page for publishing as an artifact.

Usage: python tools/render_trail.py OUTPUT.html
The markdown in docs/ stays the source of truth; this only renders it. Re-run it at every wrap-up.
Every number on the page is counted from the files; nothing is typed in by hand.
"""
from __future__ import annotations

import datetime as dt
import html
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"


def inline(md: str) -> str:
    t = html.escape(md)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)
    t = re.sub(r"(?<![\"'>=])(https://[^\s<)]+)", r'<a href="\1" target="_blank" rel="noopener">\1</a>', t)
    return t


# ---------- parsing ----------
def parse_decisions(text: str) -> list[dict]:
    out = []
    for block in re.split(r"(?m)^### ", text)[1:]:
        head, *rest = block.split("\n")
        m = re.match(r"(\d{4}-\d{2}-\d{2}) - (.*)", head.strip())
        if not m:
            continue
        fields: list[tuple[str, str]] = []
        for ln in rest:
            fm = re.match(r"- ([^:]+?):\s*(.*)", ln.strip())
            if fm:
                fields.append((fm.group(1).strip(), fm.group(2).strip()))
            elif ln.strip() and fields:
                fields[-1] = (fields[-1][0], fields[-1][1] + " " + ln.strip())
        src = next((v for k, v in fields if k.lower() == "source"), "").lower()
        why = next((v for k, v in fields if k.lower().startswith("why")), "").lower()
        out.append({"date": m.group(1), "title": m.group(2).strip(), "fields": fields,
                    "confirmed": "confirmed" in src, "inferred": "inferred" in src,
                    "norec": "reason not recorded" in why})
    return out


def parse_checklist(text: str) -> list[dict]:
    sections, cur = [], None
    for ln in text.split("\n"):
        if ln.startswith("## "):
            cur = {"title": ln[3:].strip(), "items": []}
            sections.append(cur)
        m = re.match(r"- \[( |x)\] (.*)", ln)
        if m and cur is not None:
            cur["items"].append({"done": m.group(1) == "x", "text": m.group(2)})
    return [s for s in sections if s["items"]]


def parse_bullets(text: str) -> list[str]:
    return [re.sub(r"^- ", "", ln).strip() for ln in text.split("\n") if ln.startswith("- ")]


def parse_progress(path: Path) -> dict:
    text = path.read_text()
    meta = {k: v for k, v in re.findall(r"\*\*([^*]+):\*\*\s*(.*)", text)}
    rows = []
    sec = re.search(r"## Status at a glance\n(.*?)(?=\n## )", text, re.S)
    for ln in (sec.group(1).split("\n") if sec else []):
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0] not in ("Stage", "---") and not set(cells[0]) <= set("-"):
            rows.append(cells)
    nxt = re.search(r"## Next steps\n(.*?)(?=\n## |\Z)", text, re.S)
    steps = [re.sub(r"^\d+\.\s*", "", ln).strip() for ln in (nxt.group(1).split("\n") if nxt else []) if re.match(r"\d+\.", ln)]
    return {"date": re.search(r"Progress, (\d{4}-\d{2}-\d{2})", text).group(1) if re.search(r"Progress, (\d{4}-\d{2}-\d{2})", text) else path.stem,
            "meta": meta, "rows": rows, "steps": steps}


def parse_brief(text: str) -> list[dict]:
    secs = []
    for block in re.split(r"(?m)^## ", text)[1:]:
        head, *body = block.split("\n")
        secs.append({"title": re.sub(r"^\d+\.\s*", "", head.strip()), "lines": [b for b in body if b.strip()]})
    return secs


def md_block(lines: list[str]) -> str:
    out, ul = [], False
    for ln in lines:
        if ln.startswith("- "):
            if not ul:
                out.append("<ul>"); ul = True
            out.append(f"<li>{inline(ln[2:])}</li>")
            continue
        if ul:
            out.append("</ul>"); ul = False
        m = re.match(r"\d+\.\s+(.*)", ln)
        out.append(f"<p>{inline(m.group(1) if m else ln)}</p>")
    if ul:
        out.append("</ul>")
    return "\n".join(out)


STATUS_CLASS = {"complete": "ok", "in progress": "prog", "not verified": "nv", "next": "next", "not started": "ns", "idea": "idea"}


def render() -> str:
    dec = parse_decisions((DOCS / "decisions.md").read_text())
    revisit = parse_checklist((DOCS / "revisit.md").read_text())
    later = parse_bullets((DOCS / "build-later.md").read_text())
    prog_file = sorted((DOCS / "progress").glob("*.md"))[-1]
    prog = parse_progress(prog_file)
    brief = parse_brief((DOCS / "brief.md").read_text())
    brief_head = (DOCS / "brief.md").read_text().split("\n")[1]
    open_items = sum(1 for s in revisit for i in s["items"] if not i["done"])
    done_items = sum(1 for s in revisit for i in s["items"] if i["done"])
    n_conf, n_inf, n_norec = (sum(1 for d in dec if d[k]) for k in ("confirmed", "inferred", "norec"))
    state = (DOCS / ".build-trail-state").read_text().strip() if (DOCS / ".build-trail-state").exists() else "unknown"

    status_rows = "\n".join(
        f'<tr><th scope="row">{inline(r[0])}</th><td><span class="pill {STATUS_CLASS.get(r[1].lower(), "ns")}">{html.escape(r[1])}</span></td><td>{inline(r[2])}</td></tr>'
        for r in prog["rows"])
    steps = "\n".join(f"<li>{inline(s)}</li>" for s in prog["steps"])

    dec_html = []
    for d in reversed(dec):
        badge = []
        if d["confirmed"]: badge.append('<span class="tag conf">confirmed</span>')
        if d["inferred"]: badge.append('<span class="tag inf">inferred</span>')
        if d["norec"]: badge.append('<span class="tag norec">reason not recorded</span>')
        dl = "".join(f"<dt>{html.escape(k)}</dt><dd>{inline(v)}</dd>" for k, v in d["fields"])
        dec_html.append(
            f'<details class="dec" data-conf="{int(d["confirmed"])}" data-inf="{int(d["inferred"])}" data-norec="{int(d["norec"])}">'
            f'<summary><span class="date">{d["date"][5:]}</span><span class="dtitle">{inline(d["title"])}</span><span class="tags">{"".join(badge)}</span></summary>'
            f'<dl>{dl}</dl></details>')

    rev_html = []
    for s in revisit:
        items = [i for i in s["items"] if not i["done"]]
        if not items:
            continue
        rev_html.append(f'<details class="grp"><summary>{inline(s["title"])} <span class="count">{len(items)} open</span></summary><ul>'
                        + "".join(f"<li>{inline(i['text'])}</li>" for i in items) + "</ul></details>")
    later_html = "".join(f"<li>{inline(b)}</li>" for b in later)
    brief_html = "".join(f'<details class="grp"><summary>{html.escape(s["title"])}</summary>{md_block(s["lines"])}</details>' for s in brief)

    today = dt.date.today().isoformat()
    values = dict(
        count=len(dec), conf=n_conf, inf=n_inf, norec=n_norec, open_items=open_items, done_items=done_items, shelf=len(later),
        prog_date=prog["date"], phase=inline(prog["meta"].get("Current phase", "")), milestones=inline(prog["meta"].get("Milestones", "")),
        status_rows=status_rows, steps=steps, decisions="\n".join(dec_html), revisit="\n".join(rev_html), later=later_html,
        brief=brief_html, brief_head=inline(brief_head), state=html.escape(state), today=today)
    page = TEMPLATE
    for k, v in values.items():
        page = page.replace(f"%%{k}%%", str(v))
    return page


TEMPLATE = open(Path(__file__).with_name("trail_template.html")).read() if Path(__file__).with_name("trail_template.html").exists() else ""

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    if not TEMPLATE:
        sys.exit("tools/trail_template.html is missing")
    Path(sys.argv[1]).write_text(render())
    print(f"wrote {sys.argv[1]}")

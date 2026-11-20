"""Demo server for visual checks and tools/e2e.js: a made-up library with fake Claude, Whisper and embeddings.

Run:  python tools/demo_server.py      (serves http://127.0.0.1:8798; resets .demo/ each start)
Needs the repo requirements plus: npm i playwright (only for e2e.js).
"""
import datetime as dt, json, math, struct, sys, wave
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import uvicorn
from vl.api.main import create_app
from vl.db import Category, Enrichment, Note, SoundEvent, Status, Transcript, make_session_factory
from vl.enrich.query import StructuredQuery
from vl.jobs import Deps, ImportManager
from vl.pipeline import index_note
from tests.conftest import FakeEmbedder, FakeEnricher, FakeTranscriber

root = HERE / ".demo"; root.mkdir(exist_ok=True); audio = root / "audio"; audio.mkdir(exist_ok=True)
db = root / "demo.db"
if db.exists(): db.unlink()
f = make_session_factory(db)

def wav(path, secs=14):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        frames = []
        for i in range(16000 * secs):
            t = i / 16000
            amp = 6000 * (0.3 + 0.7 * abs(math.sin(t * 1.3))) * (1 if int(t) % 5 else 0.2)
            frames.append(struct.pack("<h", int(amp * math.sin(2 * math.pi * 220 * t))))
        w.writeframes(b"".join(frames))

SEGS = [(0, "Okay, quick one before I forget. We keep running out of the same four things."),
        (3, "What if the grocery list just learned? It notices you buy oats every ten days."),
        (6, "The part I like is that it nudges you before you run out."),
        (9, "Sharing is the other thing. Sam adds stuff on his phone and mine."),
        (12, "Okay. Recording that. Done.")]
rows = [
 ("Idea: a shared grocery list that learns", "A list that notices what you buy every week and nudges you before you run out.", "Ideas", ["grocery", "app idea", "habits"], dt.datetime(2026,11,12,9,14), 0.05, [("laughter",0.52,9)], SEGS),
 ("First bike ride without training wheels", "Cheering and laughing in the driveway as she pedals off on her own.", "Family memories", ["bike", "kids"], dt.datetime(2026,10,3,17,2), 0.05, [("baby_laugh",0.71,4)], [(0,"Go go go, you're doing it!"),(5,"Look at you, no hands, well, one hand.")]),
 ("Notes after the product review", "Three follow-ups: the pricing page, onboarding copy, and the export bug.", "Work & projects", ["pricing", "onboarding"], dt.datetime(2026,10,26,11,30), 0.05, [], [(0,"Three follow-ups from the review."),(6,"First, the pricing page needs a clearer comparison.")]),
 ("Walking home, thinking about the move", "Weighing what to keep, what to leave behind, and how the new routine might feel.", "Personal reflections", ["move"], dt.datetime(2026,10,19,18,45), 0.05, [], [(0,"Walking home and thinking about the move.")]),
 ("Laughter, likely accidental recording", "Only repeated laughter with no content. Probably captured by accident.", "Other", ["laughter", "accidental"], dt.datetime(2026,11,15,22,44), 0.8, [("giggle",0.36,0)], [(0,"ha ha ha")]),
 ("Lullaby for Tessie", "A quiet lullaby sung for a child's sleep.", None, ["lullaby", "baby"], dt.datetime(2026,5,28,11,3), 0.1, [("baby_babble",0.84,6)], [(0,"hush little baby")]),
]
emb = FakeEmbedder()
with f() as s:
    cats = {c.name: c.id for c in s.query(Category)}
    for i,(t,sm,cat,tags,when,junk,snd,segs) in enumerate(rows,1):
        p = audio / f"n{i}.wav"; wav(p)
        n = Note(sha256=f"{i:064d}", path=str(p), original_name=f"New Recording {200+i}.m4a", recorded_at=when, date_source="metadata", duration_s=14.0)
        s.add(n); s.flush()
        text = " ".join(x for _, x in segs)
        s.add(Transcript(note_id=n.id, text=text, segments_json=json.dumps([{"start":a,"end":a+3,"text":b} for a,b in segs]), model_version="demo"))
        s.add(Enrichment(note_id=n.id, title=t, summary=sm, category_id=cats.get(cat), tags_json=json.dumps(tags), junk_score=junk,
                         suggested_category="Songs & lullabies" if "lullaby" in tags else None, model_version="demo"))
        for lab,c,st in snd: s.add(SoundEvent(note_id=n.id, label=lab, start_s=st, end_s=st+3, confidence=c, model_version="demo"))
    s.commit()
    for n in s.query(Note).all():
        index_note(s, n, emb); s.merge(Status(note_id=n.id, stage="sounds", state="done"))
    s.commit()

class Parser:
    def parse(self, q, cats, today):
        return StructuredQuery(semantic_text=q, keywords=[w for w in q.lower().split() if len(w) > 3])
class Reranker:
    def rerank(self, q, cands):
        return [{"id": c["id"], "why": "This is where you describe it." if i == 0 else "", "strength": ["match","partial","related"][min(i,2)]} for i,c in enumerate(cands)]

import shutil
from vl.sync import SyncManager
from vl.voicememos import audio_files
import vl.api.main as api_main

# a pretend Voice Memos folder, so sync can be exercised end to end
VM = root / "voicememos"
shutil.rmtree(VM, ignore_errors=True); VM.mkdir()
for i in range(30):
    day = i + 1
    (VM / f"202610{day:02d} 090000-{i:03d}.m4a").write_text(f"recording number {i} about topic {i}: baby sounds and ideas")
api_main.find_voice_memos = lambda: {"found": True, "path": str(VM), "count": len(audio_files(VM)), "problem": None}
shutil.rmtree(root / "state", ignore_errors=True)

holder = {}
mgr = ImportManager(f, audio, Deps(FakeTranscriber(), FakeEnricher(), emb, None), on_file_done=lambda x: holder["s"].on_file_done(x))
sync = holder["s"] = SyncManager(mgr, root / "state", source_resolver=lambda src: (VM, None), poll_seconds=3)
app = create_app(f, embedder=emb, parser=Parser(), reranker=Reranker(), audio_root=audio, import_manager=mgr,
                 cache_dir=root/"cache", upload_dir=root/"up", sync_manager=sync)
print("Demo library running at http://127.0.0.1:8798  (Ctrl+C to stop)")
uvicorn.run(app, host="127.0.0.1", port=8798, log_level="warning")

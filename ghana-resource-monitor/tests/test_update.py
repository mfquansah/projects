import csv
import shutil
import stat
import tempfile
import unittest
from datetime import date
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import Conflict, Document, IngestRun, Observation, Source
from ingest import update as upd
from ingest.load import LoadError, ROOT, load
from ingest.raw import register_document


class IngestCase(unittest.TestCase):
    """Each test gets its own copy of data/ and its own database."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.data = t / "data"
        shutil.copytree(ROOT / "data", self.data, ignore=shutil.ignore_patterns("raw", "processed"))
        self.db = t / "db" / "t.sqlite"
        load(self.db, self.data)
        self.url = f"sqlite:///{self.db}"
        self.engine = create_engine(self.url)

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    # helpers
    def edit(self, rel, fn):
        p = self.data / rel
        p.write_text(fn(p.read_text()))

    def runs(self):
        with Session(self.engine) as s:
            return s.scalars(select(IngestRun).order_by(IngestRun.id)).all()

    def live(self, metric, year):
        with Session(self.engine) as s:
            return s.scalars(select(Observation).where(Observation.metric == metric, Observation.period_start == date(year, 1, 1),
                                                       Observation.superseded_by.is_(None))).all()

    def count_obs(self):
        with Session(self.engine) as s:
            return len(s.scalars(select(Observation)).all())

    def update(self, **kw):
        return upd.run(self.url, self.data, **kw)


class IncrementalTests(IngestCase):
    def test_rerun_changes_nothing(self):
        r = self.update()
        self.assertEqual((r.status, r.changed), ("no_change", False))
        self.assertEqual(r.stats["obs_inserted"] + r.stats["obs_superseded"], 0)
        self.assertEqual([x.status for x in self.runs()], ["success", "no_change"])
        self.assertIsNotNone(self.runs()[-1].finished_at)
        self.assertIn("source_register.csv", self.runs()[-1].detail["input_sha256"])

    def test_new_year_is_inserted_and_history_untouched(self):
        before = self.count_obs()
        with open(self.data / "source_register.csv", "a", newline="") as f:
            csv.writer(f).writerow(["S99", "2026 Annual Report", "GRIDCo", "", "", "have", "peak", "high (primary)", "test"])
        with open(self.data / "gridco" / "gridco_clean_2013_2025.csv", "a", newline="") as f:
            csv.writer(f).writerow([2026, "system_peak_demand", 4600, "MW", "high", "2026_GRIDCo_Annual_Report.pdf", 26,
                                    "Single reported value, no conflict", ""])
        r = self.update()
        self.assertEqual((r.status, r.stats["obs_inserted"], r.stats["obs_superseded"], r.stats["sources_added"]),
                         ("success", 1, 0, 1))
        self.assertEqual(self.count_obs(), before + 1)
        self.assertEqual(self.live("system_peak_demand", 2026)[0].source_id, "S99")
        self.assertEqual(self.live("system_peak_demand", 2025)[0].value, 4283.0)  # untouched
        self.assertEqual(self.update().status, "no_change")  # idempotent afterwards
        backups = list((self.db.parent / "backups").glob("t-*.sqlite"))
        self.assertEqual(len(backups), 1)  # a snapshot was taken before the first change
        snap = create_engine(f"sqlite:///{backups[0]}")
        with Session(snap) as s:
            self.assertEqual(len(s.scalars(select(Observation)).all()), before)  # snapshot = state before the change
        snap.dispose()

    def test_correction_supersedes_and_keeps_history(self):
        self.edit("gridco/gridco_clean_2013_2025.csv", lambda t: t.replace("2025,system_peak_demand,4283,MW", "2025,system_peak_demand,4290,MW"))
        r = self.update()
        self.assertEqual((r.status, r.stats["obs_superseded"], r.stats["obs_inserted"]), ("success", 1, 0))
        self.assertEqual([o.value for o in self.live("system_peak_demand", 2025)], [4290.0])
        with Session(self.engine) as s:
            both = s.scalars(select(Observation).where(Observation.metric == "system_peak_demand",
                                                      Observation.period_start == date(2025, 1, 1))).all()
            self.assertEqual(sorted(o.value for o in both), [4283.0, 4290.0])  # the old value is still there
            old = next(o for o in both if o.value == 4283.0)
            new = next(o for o in both if o.value == 4290.0)
            self.assertEqual(old.superseded_by, new.id)
        self.assertEqual(self.update().status, "no_change")

    def test_conflict_can_be_resolved_later(self):
        def resolve(t):
            return "\n".join(l.replace("Unresolved", "Resolved with GRIDCo statistics") if l.startswith("2025,energy_transmitted") else l
                             for l in t.split("\n"))
        self.edit("gridco/gridco_clean_2013_2025.csv", resolve)
        r = self.update()
        self.assertEqual(r.stats["conflicts_updated"], 1)
        with Session(self.engine) as s:
            c = s.scalars(select(Conflict).where(Conflict.metric == "energy_transmitted", Conflict.period == "2025")).one()
            self.assertEqual(c.status, "resolved")

    def test_dry_run_reports_but_writes_nothing(self):
        self.edit("gridco/gridco_clean_2013_2025.csv", lambda t: t.replace("2025,system_peak_demand,4283,MW", "2025,system_peak_demand,4290,MW"))
        n_runs, n_obs = len(self.runs()), self.count_obs()
        r = self.update(dry_run=True)
        self.assertEqual((r.dry_run, r.stats["obs_superseded"]), (True, 1))
        self.assertEqual((len(self.runs()), self.count_obs()), (n_runs, n_obs))
        self.assertEqual(self.live("system_peak_demand", 2025)[0].value, 4283.0)
        self.assertFalse((self.db.parent / "backups").exists())

    def test_failed_run_rolls_back_and_is_logged(self):
        self.edit("gridco/gridco_clean_2013_2025.csv", lambda t: t.rstrip("\n") + "\n2026,system_peak_demand,1,2,3,4,5,6,7,8,9\n")
        n = self.count_obs()
        with self.assertRaises(LoadError):
            self.update()
        last = self.runs()[-1]
        self.assertEqual(last.status, "failed")
        self.assertIn("LoadError", last.error)
        self.assertEqual(self.count_obs(), n)

    def test_partial_failure_does_not_leave_half_a_load(self):
        # A good new row followed by an unparseable rejected value: nothing from this run may persist.
        self.edit("gridco/gridco_clean_2013_2025.csv", lambda t: t.replace("17034 (2020 report p16)", "17034 (garbage)"))
        n = self.count_obs()
        with self.assertRaises(LoadError):
            self.update()
        self.assertEqual(self.count_obs(), n)

    def test_row_missing_from_inputs_is_warned_never_deleted(self):
        def drop(t):
            return "\n".join(l for l in t.split("\n") if not l.startswith("2018,system_peak_demand"))
        self.edit("gridco/gridco_clean_2013_2025.csv", drop)
        n = self.count_obs()
        r = self.update()
        self.assertTrue(any("system_peak_demand 2018" in w for w in r.warnings))
        self.assertEqual(self.count_obs(), n)

    def test_upgrades_an_older_database(self):
        old = Path(self.tmp.name) / "old.sqlite"
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "migrations"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{old}")
        command.upgrade(cfg, "0001")  # a database from before the run-log columns existed
        r = upd.run(f"sqlite:///{old}", self.data, backup=False)
        self.assertEqual(r.status, "success")
        e = create_engine(f"sqlite:///{old}")
        with Session(e) as s:
            self.assertEqual(s.scalars(select(IngestRun)).one().status, "success")
        e.dispose()

    def test_cli_reports_failure_with_exit_1(self):
        self.assertEqual(upd.main(["--db", "/proc/nope/x.sqlite"]), 1)

    def test_cli_exit_codes(self):
        self.assertEqual(upd.main(["--db", str(self.db)]), 0)
        self.assertEqual(upd.main(["--db", str(self.db), "--expect-changes"]), 3)  # nothing new but new data was expected


class RawStoreTests(IngestCase):
    def reg(self, src, source_id="S02", root=None):
        with Session(self.engine) as s, s.begin():
            doc, created = register_document(s, source_id, src, raw_root=root or Path(self.tmp.name) / "raw",
                                             today=date(2026, 11, 11))
            return doc.id, created, doc.raw_path, doc.sha256

    def test_register_is_content_addressed_and_idempotent(self):
        f = Path(self.tmp.name) / "plan.pdf"
        f.write_bytes(b"%PDF-1.4 fake plan v1")
        id1, created, path, digest = self.reg(f)
        self.assertTrue(created)
        self.assertRegex(path, rf"S02/2026-11-11_{digest[:12]}_plan\.pdf$")
        stored = Path(path)
        self.assertEqual(stored.read_bytes(), f.read_bytes())
        self.assertFalse(stored.stat().st_mode & stat.S_IWUSR)  # read-only
        id2, created2, _, _ = self.reg(f)
        self.assertEqual((id2, created2), (id1, False))  # same file again: no duplicate

    def test_changed_file_is_a_new_document_beside_the_old(self):
        f = Path(self.tmp.name) / "plan.pdf"
        f.write_bytes(b"v1")
        id1, *_ = self.reg(f)
        f.write_bytes(b"v2")
        id2, created, path2, _ = self.reg(f)
        self.assertTrue(created)
        self.assertNotEqual(id1, id2)
        with Session(self.engine) as s:
            self.assertEqual(len(s.scalars(select(Document)).all()), 2)

    def test_unknown_source_and_missing_file_rejected(self):
        f = Path(self.tmp.name) / "x.pdf"
        f.write_bytes(b"x")
        with self.assertRaises(ValueError):
            self.reg(f, source_id="S777")
        with self.assertRaises(FileNotFoundError):
            self.reg(Path(self.tmp.name) / "nope.pdf")

    def test_never_overwrites_a_different_file(self):
        f = Path(self.tmp.name) / "plan.pdf"
        f.write_bytes(b"v1")
        _, _, path, digest = self.reg(f)
        stored = Path(path)
        stored.chmod(0o644)
        stored.write_bytes(b"tampered")  # simulate corruption of the stored copy
        with Session(self.engine) as s, s.begin():
            s.query(Document).delete()  # forget the record so registration tries to place the file again
        with self.assertRaises(RuntimeError):
            self.reg(f)


if __name__ == "__main__":
    unittest.main()


class ObservationFileTests(IngestCase):
    COLS = ["entity_kind", "entity_name", "parent_name", "fuel", "metric", "period_type", "year", "month", "value", "unit",
            "value_type", "capacity_type", "source_id", "page", "table_ref", "confidence", "note"]

    def write(self, *rows, name="plants.csv"):
        d = self.data / "observations"
        d.mkdir(exist_ok=True)
        with open(d / name, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(self.COLS)
            w.writerows(rows)

    @staticmethod
    def row(**kw):
        base = dict(entity_kind="plant", entity_name="Test Plant", parent_name="", fuel="gas", metric="generation_capacity",
                    period_type="annual", year=2025, month="", value=100, unit="MW", value_type="actual",
                    capacity_type="installed", source_id="S02", page="12", table_ref="Table 3", confidence="medium", note="")
        base.update(kw)
        return [base[c] for c in ObservationFileTests.COLS]

    def test_plant_capacity_loads_idempotently(self):
        self.write(self.row(), self.row(value=90, capacity_type="dependable"))
        r = self.update()
        self.assertEqual((r.status, r.stats["obs_inserted"], r.stats["entities_added"]), ("success", 2, 1))
        with Session(self.engine) as s:
            from db.models import Entity
            plant = s.scalars(select(Entity).where(Entity.kind == "plant")).one()
            self.assertEqual((plant.name, plant.attrs, plant.parent_id is not None), ("Test Plant", {"fuel": "gas"}, True))
            got = {o.capacity_type: o.value for o in s.scalars(select(Observation).where(Observation.metric == "generation_capacity"))}
            self.assertEqual(got, {"installed": 100.0, "dependable": 90.0})
        self.assertEqual(self.update().status, "no_change")

    def test_changed_value_supersedes(self):
        self.write(self.row())
        self.update()
        self.write(self.row(value=105))
        r = self.update()
        self.assertEqual((r.stats["obs_superseded"], r.stats["obs_inserted"]), (1, 0))
        self.assertEqual([o.value for o in self.live("generation_capacity", 2025)], [105.0])

    def test_monthly_rows_get_month_bounds(self):
        self.write(self.row(metric="generation", period_type="monthly", month=2, year=2024, value=300, unit="GWh", capacity_type=""))
        self.update()
        with Session(self.engine) as s:
            o = s.scalars(select(Observation).where(Observation.metric == "generation")).one()
            self.assertEqual((o.period_start, o.period_end, o.period_type), (date(2024, 2, 1), date(2024, 2, 29), "monthly"))

    def test_disagreeing_sources_are_both_kept_and_flagged_then_clear(self):
        self.write(self.row(value=100, source_id="S02"), self.row(value=110, source_id="S04"))
        r = self.update()
        self.assertEqual(r.stats["conflicts_added"], 1)
        self.assertEqual(len(self.live("generation_capacity", 2025)), 2)  # side by side, not averaged
        with Session(self.engine) as s:
            c = s.scalars(select(Conflict).where(Conflict.metric == "generation_capacity")).one()
            self.assertEqual(c.status, "open")
            self.assertIn("Auto: sources disagree", c.resolution_note)
        self.write(self.row(value=100, source_id="S02"), self.row(value=100, source_id="S04"))  # S04 corrected to agree
        self.assertEqual(self.update().stats["conflicts_updated"], 1)
        with Session(self.engine) as s:
            self.assertEqual(s.scalars(select(Conflict).where(Conflict.metric == "generation_capacity")).one().status, "resolved")

    def test_invalid_rows_name_the_file_and_line_and_load_nothing(self):
        n = self.count_obs()
        cases = [
            (self.row(source_id="S777"), "not in data/source_register.csv"),
            (self.row(source_id="S13"), "AI-generated"),
            (self.row(page=""), "page is required"),
            (self.row(capacity_type="rated"), "capacity_type"),
            (self.row(value_type="guess"), "value_type"),
            (self.row(period_type="monthly", month=""), "month 1-12"),
            (self.row(month=3), "month must be blank"),
            (self.row(value="n/a"), "must be numbers"),
            (self.row(parent_name="No Such Place"), "parent"),
            (self.row(period_type="hourly"), "hourly"),
        ]
        for row, fragment in cases:
            self.write(row)
            with self.assertRaises(LoadError, msg=fragment) as cm:
                self.update()
            self.assertIn(fragment, str(cm.exception))
            if fragment != "parent":
                self.assertIn("plants.csv line 2", str(cm.exception))
        self.assertEqual(self.count_obs(), n)

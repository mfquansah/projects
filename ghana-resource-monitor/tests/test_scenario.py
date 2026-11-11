import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import Assumption
from ingest.load import load
from model.baseline import load_series
from model.scenario import ASSUMPTIONS, Inputs, evs_needed, growth_cases, project, seed_assumptions

VEC = json.loads((Path(__file__).parent / "vectors" / "scenario.json").read_text())


class ScenarioTest(unittest.TestCase):
    def test_shared_vectors(self):  # the same file is checked by web/test/scenario.test.mjs
        for c in VEC["cases"]:
            r = project(Inputs(**c["inputs"]))
            self.assertEqual((r["below_target_year"], r["gap_year"]), (c["expect"]["below_target_year"], c["expect"]["gap_year"]))
            for e in c["expect"]["rows"]:
                got = next(x for x in r["rows"] if x["year"] == e["year"])
                for k in ("demand", "ev_mw", "total", "available", "margin"):
                    if e[k] is None:
                        self.assertIsNone(got[k])
                    else:
                        self.assertAlmostEqual(got[k], e[k], places=6)
        self.assertAlmostEqual(evs_needed(*VEC["evs_needed"]["args"]), VEC["evs_needed"]["expect"], places=6)

    def test_no_capacity_means_no_gap_claim(self):
        r = project(Inputs(2025, 4283, 0.07))
        self.assertIsNone(r["gap_year"])
        self.assertIsNone(r["below_target_year"])
        self.assertTrue(all(x["available"] is None and x["margin"] is None for x in r["rows"]))

    def test_more_capacity_delays_gap(self):
        base = Inputs(2025, 4283, 0.07, capacity_mw=4968)
        gaps = [project(Inputs(**{**base.__dict__, "added_mw_per_year": a}))["gap_year"] or 9999 for a in (0, 125, 250, 375)]
        self.assertEqual(gaps, sorted(gaps))
        self.assertLess(gaps[0], gaps[-1])

    def test_managing_ev_charging_reduces_load(self):
        a = project(Inputs(2025, 4283, 0.07))["rows"][-1]["ev_mw"]
        b = project(Inputs(2025, 4283, 0.07, ev_managed_share=0.5))["rows"][-1]["ev_mw"]
        self.assertAlmostEqual(b, a / 2)

    def test_evs_needed_roundtrip(self):
        n = evs_needed(0.01, 4283, 7, 0.4)
        self.assertAlmostEqual(n * 7 * 0.4 / 1000, 0.01 * 4283)

    def test_growth_cases_from_data_are_ordered(self):
        g = growth_cases([2019, 2020, 2021, 2022, 2023, 2024, 2025], [2804, 3090, 3246, 3469, 3618, 3952, 4283])
        self.assertLessEqual(g["low"], g["central"])
        self.assertLessEqual(g["central"], g["high"])

    def test_assumptions_seeded_once_with_rationale(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "t.sqlite"
            load(db)
            engine = create_engine(f"sqlite:///{db}")
            with Session(engine) as s:
                seed_assumptions(s)
                seed_assumptions(s)  # idempotent
                rows = s.scalars(select(Assumption)).all()
                self.assertEqual({a.name for a in rows}, set(ASSUMPTIONS))
                self.assertTrue(all(a.rationale for a in rows))
            engine.dispose()


if __name__ == "__main__":
    unittest.main()

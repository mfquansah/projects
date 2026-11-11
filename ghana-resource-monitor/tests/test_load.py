import tempfile
import unittest
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import Conflict, Entity, Observation, Source
from db.ops import supersede
from ingest.load import LoadError, SOURCE_COLS, load, read_csv, source_tier


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "t.sqlite"
        self.counts = load(self.db)
        self.engine = create_engine(f"sqlite:///{self.db}")
        self.s = Session(self.engine)

    def tearDown(self):
        self.s.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def _obs(self, **kw):
        base = dict(metric="system_peak_demand", entity_id=1, period_start=date(2025, 1, 1),
                    period_end=date(2025, 12, 31), period_type="annual", value=4283, unit="MW",
                    value_type="actual", source_id="S01", confidence="high")
        base.update(kw)
        return Observation(**base)

    def test_counts(self):
        self.assertEqual(self.counts[:2], (25, 90))
        self.assertEqual([(g[0], g[1]) for g in self.counts[2]], [(2024, 'system_availability')])  # a gap stays a gap

    def test_verified_annual_peaks(self):
        # GRIDCo annual reports 2013-2025 via data/gridco/gridco_clean_2013_2025.csv
        rows = self.s.execute(select(Observation.period_start.label("d"), Observation.value)
                              .where(Observation.metric == "system_peak_demand")
                              .order_by(Observation.period_start)).all()
        self.assertEqual([(r.d.year, r.value) for r in rows],
                         [(2013, 1942.9), (2014, 1970.0), (2015, 1933.0), (2016, 1997.0), (2017, 2192.15),
                          (2018, 2525.0), (2019, 2804.0), (2020, 3090.0), (2021, 3246.0), (2022, 3469.0),
                          (2023, 3618.0), (2024, 3952.0), (2025, 4283.0)])

    def _live(self, metric, year):
        return self.s.scalars(select(Observation).where(
            Observation.metric == metric, Observation.period_start == date(year, 1, 1),
            Observation.superseded_by.is_(None))).all()

    def test_energy_2019_2022_use_the_cross_checked_values(self):
        # The data owner's loss-volume / loss-% test rejected the other candidates.
        for year, value in [(2019, 17887.0), (2020, 19716.59), (2021, 21466.0), (2022, 22478.46)]:
            live = self._live("energy_transmitted", year)
            self.assertEqual([o.value for o in live], [value])
            self.assertEqual(live[0].confidence, "high")

    def test_rejected_values_are_kept_but_never_live(self):
        every = self.s.scalars(select(Observation).where(
            Observation.metric == "energy_transmitted", Observation.period_start == date(2019, 1, 1))).all()
        self.assertEqual(sorted(o.value for o in every), [17034.0, 17887.0])  # both stored
        self.assertEqual([o.value for o in every if o.superseded_by is None], [17887.0])  # one live
        c = self.s.scalars(select(Conflict).where(Conflict.metric == "energy_transmitted", Conflict.period == "2019")).one()
        self.assertEqual((c.status, len(c.observation_ids)), ("resolved", 2))

    def test_unresolved_energy_totals_are_open_and_low_confidence(self):
        for year in (2024, 2025):
            self.assertEqual(self._live("energy_transmitted", year)[0].confidence, "low")
            c = self.s.scalars(select(Conflict).where(Conflict.metric == "energy_transmitted", Conflict.period == str(year))).one()
            self.assertEqual(c.status, "open")

    def test_network_assets_are_not_generation_capacity(self):
        rows = self.s.scalars(select(Observation).where(Observation.metric == "transformation_capacity")).all()
        self.assertTrue(rows)
        self.assertTrue(all(o.unit == "MVA" and o.capacity_type is None for o in rows))

    def test_each_value_cites_its_own_annual_report(self):
        o = self._live("system_peak_demand", 2013)[0]
        self.assertEqual(self.s.get(Source, o.source_id).name, "2013 Annual Report")
        self.assertEqual(self._live("system_peak_demand", 2025)[0].source_id, "S01")

    def test_peak_is_annual_coincident_actual(self):
        rows = self.s.scalars(select(Observation).where(Observation.metric == "system_peak_demand")).all()
        self.assertTrue(rows)
        for o in rows:
            self.assertEqual((o.period_type, o.value_type, o.capacity_type),
                             ("annual", "actual", "peak_coincident"))

    def test_every_observation_has_provenance(self):
        for o in self.s.scalars(select(Observation)).all():
            self.assertTrue(o.source_id and o.page and o.confidence, o.id)

    def test_source_tiers(self):
        tiers = {s.id: s.tier for s in self.s.scalars(select(Source)).all()}
        self.assertEqual(tiers["S01"], "primary")
        self.assertEqual(tiers["S10"], "secondary")
        self.assertEqual(tiers["S13"], "ai_summary")
        self.assertEqual(source_tier("unreliable; do not cite"), "ai_summary")

    def test_unreliable_source_is_not_cited(self):
        self.assertEqual(self.s.scalars(select(Observation).where(Observation.source_id == "S13")).all(), [])

    def test_invalid_value_type_rejected(self):
        self.s.add(self._obs(value_type="guess"))
        with self.assertRaises(IntegrityError):
            self.s.flush()

    def test_period_order_enforced(self):
        self.s.add(self._obs(period_start=date(2025, 12, 31), period_end=date(2025, 1, 1), source_id="S10"))
        with self.assertRaises(IntegrityError):
            self.s.flush()

    def test_conflicting_sources_coexist_but_live_duplicates_do_not(self):
        ghana = self.s.scalars(select(Entity)).one()
        self.s.add(self._obs(entity_id=ghana.id, value=4280, source_id="S10", confidence="medium"))
        self.s.flush()  # different source: stored side by side
        self.s.add(self._obs(entity_id=ghana.id, value=4290, source_id="S10", confidence="medium"))
        with self.assertRaises(IntegrityError):  # same source, still live: rejected
            self.s.flush()

    def test_supersede_keeps_history_and_one_live_row(self):
        ghana = self.s.scalars(select(Entity)).one()
        q = select(Observation).where(Observation.metric == "system_peak_demand",
                                      Observation.period_start == date(2025, 1, 1))
        old = self.s.scalars(q).one()
        new = supersede(self.s, old, self._obs(entity_id=ghana.id, value=4284, note="correction",
                                               confidence="medium"))
        rows = self.s.scalars(q).all()
        self.assertEqual(len(rows), 2)  # history kept
        self.assertEqual(old.superseded_by, new.id)
        self.assertEqual([o.value for o in rows if o.superseded_by is None], [4284.0])
        with self.assertRaises(ValueError):
            supersede(self.s, old, self._obs(entity_id=ghana.id, value=1))

    def test_malformed_csv_rejected(self):
        bad = Path(self.tmp.name) / "bad.csv"
        bad.write_text(",".join(SOURCE_COLS) + "\nS99,a,b,c,d,e,f,g,h,EXTRA\n")
        with self.assertRaises(LoadError):
            read_csv(bad, SOURCE_COLS)


if __name__ == "__main__":
    unittest.main()

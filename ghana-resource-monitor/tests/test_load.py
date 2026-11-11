import sqlite3
import tempfile
import unittest
from pathlib import Path

from ingest.load import ROOT, LoadError, load, read_csv, SOURCE_COLS


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "t.sqlite"
        self.counts = load(self.db)
        self.con = sqlite3.connect(self.db)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_counts(self):
        self.assertEqual(self.counts, (13, 23))

    def test_verified_annual_peaks(self):
        # GRIDCo 2025 Annual Report, pp. 25-26 (see CLAUDE.md "Verified so far")
        rows = self.con.execute(
            "SELECT year, value FROM observations WHERE metric='system_peak_demand' ORDER BY year").fetchall()
        self.assertEqual(rows, [(2019, 2804.0), (2020, 3090.0), (2021, 3246.0), (2022, 3469.0),
                                (2023, 3618.0), (2024, 3952.0), (2025, 4283.0)])

    def test_peak_is_annual_coincident_actual(self):
        bad = self.con.execute(
            """SELECT COUNT(*) FROM observations WHERE metric='system_peak_demand'
               AND NOT (period_type='annual' AND value_type='actual' AND capacity_type='peak_coincident')""").fetchone()[0]
        self.assertEqual(bad, 0)

    def test_every_observation_has_provenance(self):
        n = self.con.execute(
            "SELECT COUNT(*) FROM observations WHERE source_id IS NULL OR pdf_page IS NULL OR pdf_page='' OR confidence=''").fetchone()[0]
        self.assertEqual(n, 0)

    def test_unreliable_source_is_not_cited(self):
        n = self.con.execute("SELECT COUNT(*) FROM observations WHERE source_id='S13'").fetchone()[0]
        self.assertEqual(n, 0)

    def test_monthly_requires_month(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute(
                "INSERT INTO observations (metric,year,value,unit,period_type,value_type,source_id,confidence)"
                " VALUES ('x',2025,1,'MW','monthly','actual','S01','high')")

    def test_conflicting_sources_coexist_but_duplicates_do_not(self):
        ins = ("INSERT INTO observations (metric,year,value,unit,period_type,value_type,source_id,confidence)"
               " VALUES ('system_peak_demand',2025,?,'MW','annual','actual',?,'low')")
        self.con.execute(ins, (4280, "S10"))  # different source: stored side by side
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute(ins, (4290, "S10"))  # same source again: rejected

    def test_malformed_csv_rejected(self):
        bad = Path(self.tmp.name) / "bad.csv"
        bad.write_text(",".join(SOURCE_COLS) + "\nS99,a,b,c,d,e,f,g,h,EXTRA\n")
        with self.assertRaises(LoadError):
            read_csv(bad, SOURCE_COLS)


if __name__ == "__main__":
    unittest.main()

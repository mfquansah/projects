import json
import tempfile
import unittest
from pathlib import Path

from ingest.export import export
from ingest.load import load
from model.baseline import run


class ExportTest(unittest.TestCase):
    def test_export_matches_report_and_never_invents_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, out = Path(tmp) / "t.sqlite", Path(tmp) / "energy.json"
            load(db)
            with self.assertRaises(RuntimeError):  # no stored forecast yet -> refuse to export
                export(db, out)
            run(db)
            p = export(db, out)
            self.assertEqual(json.loads(out.read_text())["derived"]["peak_latest"], 4283.0)
            self.assertAlmostEqual(p["derived"]["peak_yoy_pct"], 8.4, places=1)  # GRIDCo: +8.4%
            self.assertAlmostEqual(p["derived"]["energy_yoy_pct"], 9.15, places=2)  # GRIDCo: +9.15%
            self.assertAlmostEqual(p["derived"]["peak_growth_since_first_pct"], 52.7, places=1)  # GRIDCo: +52.7%
            self.assertIsNone(p["capacity"])  # unverified capacity must not reach the site
            self.assertNotIn("S13", {s["id"] for s in p["sources"]})  # AI summary never cited


if __name__ == "__main__":
    unittest.main()

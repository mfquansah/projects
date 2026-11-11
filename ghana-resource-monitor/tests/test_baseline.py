import math
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import ForecastOutput, ModelRun, Observation
from ingest.load import load
from model.baseline import MODELS, backtest, loglinear_interval, predict_point, run


class BaselineMath(unittest.TestCase):
    def test_loglinear_recovers_exact_growth(self):
        years = list(range(2019, 2026))
        vals = [1000 * 1.07 ** i for i in range(7)]
        pred = predict_point("loglinear", years, vals, [2026, 2027])
        self.assertAlmostEqual(pred[0], 1000 * 1.07 ** 7, places=6)
        self.assertAlmostEqual(pred[1], 1000 * 1.07 ** 8, places=6)

    def test_interval_orders_and_widens_with_horizon(self):
        years = list(range(2019, 2026))
        vals = [2804, 3090, 3246, 3469, 3618, 3952, 4283]
        (a, b), fit = loglinear_interval(years, vals, [2026, 2032])[0], loglinear_interval(years, vals, [2026])[1]
        for lo, mid, hi in (a, b):
            self.assertLess(lo, mid)
            self.assertLess(mid, hi)
        self.assertGreater(b[2] / b[0], a[2] / a[0])  # far horizon has a wider relative band
        self.assertAlmostEqual(fit["annual_growth"], 0.0691, places=3)

    def test_backtest_never_peeks_at_future(self):
        years = list(range(2019, 2026))
        vals = [2804, 3090, 3246, 3469, 3618, 3952, 4283]
        summary, rows = backtest(years, vals)
        self.assertEqual(set(summary), set(MODELS))
        for r in rows:
            self.assertGreater(r["target"], r["origin"])
        # Changing a value after the origin must not change that origin's forecast
        vals2 = vals[:5] + [99999, 99999]
        _, rows2 = backtest(years, vals2)
        pick = lambda rs: [r["forecast"] for r in rs if r["origin"] == 2023 and r["h"] == 1 and r["model"] == "loglinear"]
        self.assertEqual(pick(rows), pick(rows2))


class BaselineRun(unittest.TestCase):
    def test_run_stores_reproducible_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "t.sqlite"
            load(db)
            res = run(db, horizon=3)
            self.assertEqual(sorted(res["forecast"]), [2026, 2027, 2028])
            engine = create_engine(f"sqlite:///{db}")
            with Session(engine) as s:
                mr = s.scalars(select(ModelRun)).one()
                self.assertEqual(mr.inputs_snapshot["series"]["2025"], 4283.0)
                outs = s.scalars(select(ForecastOutput)).all()
                self.assertEqual(len(outs), 3)
                self.assertTrue(all(o.p10 < o.p50 < o.p90 for o in outs))
                # forecasts never overwrite observations
                self.assertEqual(len(s.scalars(select(Observation)).all()), 23)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()

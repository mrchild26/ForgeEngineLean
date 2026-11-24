import contextlib
import io
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

import bench
import optimize
from src.config import ROOT


class TestBenchOverride(unittest.TestCase):
    def test_an_override_changes_the_result_and_is_recorded_in_the_output(self):
        with TemporaryDirectory() as directory:
            cases, results = Path(directory) / "cases", Path(directory) / "results"
            shutil.copytree(ROOT / "cases" / "original", cases / "original")
            reports = {}
            for name, args in (("default", []), ("slow", ["--set", "cost_model:removal_rate_mm3_min=1000"])):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    bench.main(["--cases", str(cases), "--results", str(results / name), *args])
                reports[name] = (json.loads((results / name / "original.json").read_text(encoding="utf-8")), out.getvalue())
        (default, _), (slow, printed) = reports["default"], reports["slow"]
        self.assertNotIn("overrides", default)
        self.assertEqual(slow["overrides"], [{"file": "cost_model", "key": "removal_rate_mm3_min", "from": 50000, "to": 1000}])
        self.assertIn("Override (in memory only): cost_model:removal_rate_mm3_min 50000 -> 1000", printed)
        c2 = lambda report: report["cost"]["checks"]["C2_manufacturing_cost"]["result"]["value"]  # noqa: E731
        self.assertAlmostEqual(c2(slow), 671.183158, places=6)  # the old default reproduces the old repo
        self.assertAlmostEqual(c2(default), 153.07, places=2)  # manufacturing_review.md, 50000 mm3/min
        self.assertEqual(slow["cost"]["checks"]["C1_changed_part_cost"]["inputs"]["removal_rate"]["value"], 1000)


class TestOptimizerSummary(unittest.TestCase):
    def test_the_default_output_is_a_summary_and_verbose_prints_every_row(self):
        row = {"delta_total_eur": -1.0, "f4_bound": 1.0, "f7_safety_factor": 1.5, "g10_engagement_d": 2.0}
        rows = [{**row, "option_id": "a", "verdict": "ACCEPT", "fail_ids": ""},
                {**row, "option_id": "b", "verdict": "REJECT", "fail_ids": "F4_deflection_ratio_bound G10_thread_engagement"},
                {**row, "option_id": "c", "verdict": "REJECT", "fail_ids": "F4_deflection_ratio_bound"}]
        short = optimize.summary_lines(rows, "results/options.csv")
        self.assertEqual(len(short), 3)  # header, the ACCEPT row, the summary
        self.assertEqual(short[-1], "Options failing each check (of 3): F4: 2, G10: 1. Full table: results/options.csv (or --verbose).")
        self.assertEqual(len(optimize.summary_lines(rows, "results/options.csv", verbose=True)), 4)  # header + every row

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.records import (FAIL, INFO, PASS, UNCHANGED, calculation, change_proof, grader_summary, measured, validate_record,
                         validate_report, value_record, write_json)


def record(value=1.0, limit=2.0, **kwargs):
    return calculation("difference = measured - required", {"measured": measured(1.0, "mm")}, value, limit, "mm", **kwargs)


class TestRecords(unittest.TestCase):
    def test_grader_result_without_a_recorded_formula_fails(self):
        """Assignment: one test must fail if a grader gives a result without a recorded formula."""
        for formula in (None, "", "   "):
            bad = {**record(), "formula": formula}
            with self.subTest(formula=formula), self.assertRaisesRegex(ValueError, "formula"):
                validate_record(bad)
        missing = record()
        del missing["formula"]
        report = {grader: {"checks": {}, "summary": grader_summary(grader, {}, {})} for grader in ("function", "fit", "cost")}
        report["fit"]["checks"]["G99"] = missing
        with self.assertRaisesRegex(ValueError, "formula"):
            validate_report(report)
        with self.assertRaisesRegex(ValueError, "formula"):
            calculation("", {"measured": measured(1.0, "mm")}, 1.0, 2.0, "mm")

    def test_status_follows_the_threshold_and_unknown_is_not_demonstrable(self):
        self.assertEqual(record(1.0, 2.0)["status"], PASS)
        self.assertEqual(record(3.0, 2.0)["status"], FAIL)
        self.assertEqual(record(2.0, 2.0, operator="<")["status"], FAIL)
        self.assertEqual(record(None, 2.0)["status"], FAIL)
        with self.assertRaisesRegex(ValueError, "disagrees"):
            validate_record({**record(3.0, 2.0), "status": PASS})
        with self.assertRaisesRegex(ValueError, "unit"):
            calculation("x", {"a": measured(1, "")}, 1, 2, "mm")

    def test_unchanged_needs_a_proof_and_its_proof_check_must_pass(self):
        with self.assertRaisesRegex(ValueError, "proof"):
            record(None, 2.0, proof={"checks": ["G0"], "text": " "})
        with self.assertRaisesRegex(ValueError, "proof"):
            record(None, 2.0, proof={"checks": [], "text": "no check named"})
        unchanged = record(None, 2.0, proof={"checks": ["G0", "G3"], "text": "only ZXVerbinder changed"})
        self.assertEqual(unchanged["status"], UNCHANGED)
        checks = {"F7": unchanged}
        self.assertEqual(grader_summary("function", checks, {"G0": PASS, "G3": PASS})["status"], PASS)
        failed = grader_summary("function", checks, {"G0": PASS, "G3": FAIL})
        self.assertEqual((failed["status"], failed["failed_checks"]), (FAIL, ["F7"]))
        self.assertEqual(grader_summary("function", {"F1": record(3.0, 2.0)}, {})["failed_checks"], ["F1"])
        hidden = record(3.0, 2.0, proof={"checks": ["G0"], "text": "the original fails too"})  # computed and failing
        self.assertEqual((hidden["status"], "proof" in hidden), (FAIL, False))

    def test_change_proof_names_every_change_and_its_conditions_must_pass(self):
        changes = [("trim", {"F6": "not in the LC2 path"}), ("S1", {"F6": "load reduced"})]
        proof = change_proof("F6", changes, ["G0"], [record(1.0, 2.0)])
        self.assertIn("trim: not in the LC2 path", proof["text"])
        self.assertIn("S1: load reduced", proof["text"])
        self.assertIsNone(change_proof("F6", changes + [("S3", {"F5": "other check"})], ["G0"]))  # S3 gives no F6 reason
        holds = record(None, 2.0, proof=proof)
        self.assertEqual(grader_summary("function", {"F6": holds}, {"G0": PASS})["status"], PASS)
        broken = record(None, 2.0, proof=change_proof("F6", changes, ["G0"], [record(3.0, 2.0)]))  # condition FAILs
        self.assertEqual(grader_summary("function", {"F6": broken}, {"G0": PASS})["failed_checks"], ["F6"])

    def test_info_records_have_no_threshold_and_are_not_graded(self):
        info = value_record("drive = -force_x", {"force_x": measured(200, "N")}, -200, "N")
        self.assertEqual((info["status"], info["threshold"]["value"]), (INFO, None))
        report = {grader: {"checks": {}, "summary": grader_summary(grader, {}, {})} for grader in ("function", "fit", "cost")}
        report["function"]["checks"]["F9"] = info
        with self.assertRaisesRegex(ValueError, "PASS, FAIL or UNCHANGED"):
            validate_report(report)

    def test_write_json_rejects_non_finite_numbers(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "case.json"
            write_json(path, {"value": 1.5})
            self.assertTrue(path.is_file())
            with self.assertRaises(ValueError):
                write_json(Path(directory) / "bad.json", {"value": float("nan")})
            self.assertFalse((Path(directory) / "bad.json").exists())

import copy
import unittest

from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.gp import gp_Trsf, gp_Vec

from src import cache as cache_module
from src.config import ROOT, load_config
from src.geometry import read_step_solids
from src.grade import Case, assign_solids, connector_geometry, evaluate_case, option_solids, substitution_shapes
from src.function_eval import lc2_drive
from src.load_path import analyze
from src.records import FAIL, PASS, UNCHANGED, validate_report

UNCHANGED_IDS = {"F5_LC1_assembly_yield", "F6_LC2_assembly_yield", "G6_IF3_z_travel", "G12_NP2_metric_threads"}
F7, G6, G9, G10 = "F7_z_ball_nut_capacity", "G6_IF3_z_travel", "G9_envelope", "G10_thread_engagement"
S1_TORQUE_FORCE = 6800 * 0.9 / 3  # 2,040 N: the YAML LC2 force scaled by the torque ratio of the 0.9 Nm motor
OLD_RATE = "cost_model:removal_rate_mm3_min=1000"  # the earlier implementation's reference numbers use the old default


def statuses(report):
    return {k: r["status"] for g in ("function", "fit", "cost") for k, r in report[g]["checks"].items()}


def value(report, grader, key):
    return report[grader]["checks"][key]["result"]["value"]


def failed(report):
    return {k for g in ("function", "fit", "cost") for k in report[g]["summary"]["failed_checks"]}


class TestGraders(unittest.TestCase):
    """Runs on the cache; reference values from the earlier implementation, at the old removal rate 1000 mm3/min."""

    @classmethod
    def setUpClass(cls):
        cls.cache, cls.config = cache_module.load(), load_config(overrides=[OLD_RATE])
        cls.subs = {s["id"]: s for s in cls.config.substitutions}
        cls.two = option_solids(cls.cache, cls.config.rule, 2)
        cls.geometry = connector_geometry(cls.cache.connectors, cls.two, cls.cache, cls.config)
        cls.original = evaluate_case(Case("original", cls.cache.connectors, reference=True), cls.cache, cls.config)
        cls.best = cls.option(2, ())
        cls.winner = cls.option(2, ("S1", "S3", "S4"))
        cls.failing = evaluate_case(Case("failing", read_step_solids(ROOT / "cases" / "failing" / "overtrimmed_zxverbinder.step")),
                                    cls.cache, cls.config)

    @classmethod
    def option(cls, trim, ids, subs=None, extra=None, config=None):
        subs = subs or cls.subs
        replaced = {}
        for i in ids:
            declared = substitution_shapes(subs[i], cls.cache)
            replaced.update(assign_solids(cls.cache, declared, [s for _, _, s in declared if s is not None]))
        replaced.update(extra or {})
        return evaluate_case(Case(f"trim_{trim:02d}mm+{'+'.join(ids)}", cls.two, trim, tuple(subs[i] for i in ids), replaced),
                             cls.cache, config or cls.config, cls.geometry)

    def test_registration_fits_the_carriages_and_g9_is_absolute(self):
        datum = self.original["datum"]
        self.assertTrue(datum["accepted"])
        self.assertLessEqual(max(datum["carriage_residuals_mm"]), 0.5)
        self.assertEqual(datum["rotation"], [[1, 0, 0], [0, -1, 0], [0, 0, -1]])  # 180 deg about X
        self.assertAlmostEqual(datum["tool"]["tool_tip_z"], 68.626, places=3)
        self.assertAlmostEqual(datum["tool"]["stick_out_mm"], 43.759, places=3)
        for report, margin in ((self.original, "margin_min_x"), (self.best, "margin_min_x"), (self.winner, "margin_min_x")):
            self.assertEqual(statuses(report)[G9], PASS)
            self.assertEqual(value(report, "fit", G9), report["fit"]["checks"][G9]["inputs"][margin]["value"])
        self.assertAlmostEqual(self.original["fit"]["checks"][G9]["inputs"]["margin_max_z"]["value"], 16.5, places=6)
        self.assertAlmostEqual(self.winner["fit"]["checks"][G9]["inputs"]["margin_max_z"]["value"], 40.5, places=5)  # S1

    def test_g6_carries_the_measured_travel_and_fails_a_raised_requirement(self):
        self.assertEqual((statuses(self.winner)[G6], value(self.winner, "fit", G6)), (UNCHANGED, 134.0911795704385))
        with self.assertWarnsRegex(UserWarning, "IF3_z_travel.* source is 'published"):
            raised = load_config(overrides=[OLD_RATE, "requirements:interfaces_that_must_not_change.IF3_z_travel.travel_mm.value=150"])
        report = self.option(2, ("S1", "S3", "S4"), config=raised)
        self.assertEqual((statuses(report)[G6], report["verdict"]), (FAIL, "REJECT"))  # 134.09 < 150
        shift = gp_Trsf()
        shift.SetTranslation(gp_Vec(0, 40.0, 0))  # into the Z-moving set: the proof condition fails, so nothing is carried
        moved = evaluate_case(Case("moved", tuple(s.Moved(TopLoc_Location(shift)) for s in self.cache.connectors)),
                              self.cache, self.config, self.geometry)
        self.assertEqual((statuses(moved)[G6], value(moved, "fit", G6)), (FAIL, None))

    def test_default_removal_rate_gives_the_reviewed_made_part_saving(self):
        report = self.option(2, ("S1", "S3", "S4"), config=load_config())  # default 50000 mm3/min
        c3 = report["cost"]["checks"]["C3_cost_delta"]
        self.assertAlmostEqual(c3["inputs"]["made_parts_delta"]["value"], -0.158397, places=6)  # manufacturing_review.md
        self.assertAlmostEqual(c3["result"]["value"], -9.134517, places=6)

    def test_reports_are_complete_and_valid(self):
        for report in (self.original, self.best, self.failing, self.winner):
            validate_report(report)
            self.assertEqual(sum(len(report[g]["checks"]) + 1 for g in ("function", "fit", "cost")), 31)
            for record in (r for g in ("function", "fit", "cost") for r in report[g]["checks"].values()):
                self.assertTrue(record["formula"])
        for report in (self.original, self.best, self.failing, self.winner):
            self.assertEqual({k for k, s in statuses(report).items() if s == UNCHANGED}, UNCHANGED_IDS)

    def test_original_is_the_reference_and_fails_its_computed_checks(self):
        self.assertEqual(self.original["verdict"], "REFERENCE")
        self.assertEqual(value(self.original, "cost", "C3_cost_delta"), 0.0)
        self.assertEqual((statuses(self.original)[F7], value(self.original, "function", F7)), (FAIL, 3000 / 6800))  # 0.44 < 1.2
        self.assertEqual((statuses(self.original)[G10], value(self.original, "fit", G10)), (FAIL, 0.0))
        self.assertEqual([self.original[g]["summary"]["failed_checks"] for g in ("function", "fit", "cost")],
                         [[F7], [G10], ["C3_cost_delta"]])
        self.assertEqual(len(self.original["baseline_findings"]), 5)

    def test_trim_only_keeps_the_old_numbers_and_is_rejected_for_the_ball_nut_and_the_clamp_screws(self):
        self.assertEqual(self.best["verdict"], "REJECT")
        self.assertEqual({k for k, s in statuses(self.best).items() if s == FAIL}, {F7, G10})
        self.assertIn(F7, self.best["function"]["summary"]["failed_checks"])
        self.assertAlmostEqual(-value(self.best, "cost", "C3_cost_delta"), 3.6863967999861416, places=6)
        self.assertAlmostEqual(value(self.best, "function", "F4_deflection_ratio_bound"), 1.0986040519982692, places=9)
        for key, expected in (("F1_connector_tear_out", 0.434098), ("F2_connector_bearing", 1.190476),
                              ("F3_connector_net_section", 0.571429)):
            self.assertAlmostEqual(value(self.best, "function", key), expected, places=6)
        self.assertAlmostEqual(value(self.best, "fit", "G15_NP5_mass"), -0.0119168, places=7)
        self.assertAlmostEqual(value(self.best, "fit", "G14_NP4_parcel"), -252.0, places=6)
        c1 = self.best["cost"]["checks"]["C1_changed_part_cost"]
        self.assertAlmostEqual(c1["inputs"]["occurrence_1.total"]["value"], 40.645790, places=6)  # hand calculation
        self.assertAlmostEqual(c1["result"]["value"], 81.291579, places=6)

    def test_three_mm_fails_only_the_deflection_bound(self):
        report = evaluate_case(Case("trim_03mm", option_solids(self.cache, self.config.rule, 3), 3), self.cache, self.config)
        self.assertEqual(report["verdict"], "REJECT")
        self.assertEqual({k for k, s in statuses(report).items() if s == FAIL}, {"F4_deflection_ratio_bound", F7, G10})

    def test_failing_case_fails_exactly_the_planned_checks(self):
        found = statuses(self.failing)
        self.assertEqual(self.failing["verdict"], "REJECT")
        self.assertEqual({k for k, s in found.items() if s == FAIL},
                         {"F1_connector_tear_out", "F4_deflection_ratio_bound", "G3_protected_core", F7, G10})
        for key in ("F2_connector_bearing", "F3_connector_net_section", "G0_change_confined_to_rule", "G1_placed_copies",
                    "G2_removal_only", "G15_NP5_mass", "C3_cost_delta"):
            self.assertEqual(found[key], PASS, key)
        self.assertAlmostEqual(value(self.failing, "fit", "G3_protected_core"), 4041.275356, places=5)
        self.assertAlmostEqual(self.failing["function"]["checks"]["F4_deflection_ratio_bound"]["inputs"]["bound_+Y"]["value"],
                               2.647443303780922, places=9)
        self.assertAlmostEqual(value(self.failing, "cost", "C3_cost_delta"), -34.49187791881582, places=6)

    def test_unchanged_records_fail_when_their_proof_check_fails(self):
        shift = gp_Trsf()
        shift.SetTranslation(gp_Vec(0, 1.0, 0))  # breaks G0 (Y drift), so no UNCHANGED proof holds
        moved = tuple(s.Moved(TopLoc_Location(shift)) for s in self.cache.connectors)
        # F1-F4 and G1-G3 reuse the 2 mm geometry: this test is about G0 and the proofs that depend on it.
        report = evaluate_case(Case("moved", moved), self.cache, self.config, self.geometry)
        self.assertEqual(statuses(report)["G0_change_confined_to_rule"], FAIL)
        self.assertTrue({"F5_LC1_assembly_yield", "F6_LC2_assembly_yield", "F7_z_ball_nut_capacity"}
                        <= set(report["function"]["summary"]["failed_checks"]))
        self.assertEqual(report["verdict"], "REJECT")

    def test_winner_with_all_three_substitutions(self):
        r = self.winner
        self.assertEqual(r["verdict"], "ACCEPT")
        g0 = r["fit"]["checks"]["G0_change_confined_to_rule"]
        self.assertEqual((g0["status"], sorted(g0["declared_changes"]), g0["undeclared_changed_parts"]),
                         (PASS, ["S1", "S3", "S4", "zxverbinder_trim"], []))
        self.assertEqual(g0["declared_changes"]["S1"], ["Nema 23 76x56", "StepperWire"])
        self.assertAlmostEqual(g0["inputs"]["S1.shaft_tip_to_screw_journal_gap"]["value"], 3.5, places=6)
        f7 = r["function"]["checks"]["F7_z_ball_nut_capacity"]
        self.assertEqual(f7["status"], PASS)
        self.assertAlmostEqual(f7["result"]["value"], 3000 / S1_TORQUE_FORCE, places=9)  # 1.4706 >= 1.2
        f6 = r["function"]["checks"]["F6_LC2_assembly_yield"]
        self.assertEqual((f6["status"], f6["proof"]["holds"], f6["proof"]["conditions"][0]["status"]), (UNCHANGED, True, PASS))
        for change in ("zxverbinder_trim:", "S1:", "S3:", "S4:"):
            self.assertIn(change, r["function"]["checks"]["F5_LC1_assembly_yield"]["proof"]["text"])
        g10 = r["fit"]["checks"]["G10_thread_engagement"]
        self.assertEqual(g10["status"], PASS)
        self.assertAlmostEqual(g10["result"]["value"], 2.0, places=5)  # M5 x 65: 10 mm = 2.0 d; M8 x 110: 2.25 d
        self.assertAlmostEqual(g10["inputs"]["rear_clamp_m8_1.engagement"]["value"], 18.0, places=9)
        self.assertAlmostEqual(g10["inputs"]["motor_m5_1.engagement"]["value"], 10.0, places=5)
        self.assertEqual(statuses(r)["G17_bought_parts"], PASS)
        c3 = r["cost"]["checks"]["C3_cost_delta"]
        deltas = {"S1": -(28.70 - 17.13) / 1.1127, "S3": 4 * (64.96 / 1.19 / 100 - 30.06 / 100),
                  "S4": 4 * (17.98 / 100 - 8.28 / 1.19 / 100)}
        for sub, expected in deltas.items():
            self.assertAlmostEqual(c3["inputs"][f"{sub}.bought_delta"]["value"], expected, places=9, msg=sub)
        self.assertAlmostEqual(c3["inputs"]["S3.price_to.piece_price"]["value"], 64.96 / 1.19 / 100, places=12)
        self.assertAlmostEqual(c3["result"]["value"], -3.6863968 + sum(deltas.values()), places=6)
        self.assertEqual(sorted(f["check"] for f in r["compliance"]), ["F5/F6", "G6"])
        info = r["information"]
        self.assertAlmostEqual(info["z_speed_cutting"]["inputs"]["rpm"]["value"], 783.1, places=1)
        self.assertAlmostEqual(info["z_speed_cutting"]["result"]["value"], 1957.8, places=1)
        self.assertAlmostEqual(info["z_speed_rapid"]["result"]["value"], 3248.5, places=1)

    def test_live_changes_of_stick_out_lc2_inputs_and_nut_rating_reach_the_graders(self):
        with self.assertWarnsRegex(UserWarning, "tool_tip.z_mm 68.0 differs .* using 48.0"):
            path = analyze(self.cache, load_config(overrides=["requirements:reference_points.tool_stick_out_mm.value=50"]))
        self.assertEqual((path["points_mm"]["tool_tip"][2], path["tool_tip_z"]["inputs"]["tool_stick_out"]["value"]), (48.0, 50))
        halved = 2 * 3.141592653589793 * 3 * 0.9 / 0.005 / 6786  # pitch 5 mm: derived 3,392.9 N against the YAML's 6,786 N
        for override, s1 in ((None, S1_TORQUE_FORCE), ("requirements:load_cases.LC2_crash.force_N.value=8000", 2400),
                             ("requirements:load_cases.LC2_crash.derivation.screw_pitch_mm.value=5", S1_TORQUE_FORCE * halved)):
            if override and "screw_pitch" in override:  # a published value: the override must warn
                with self.assertWarnsRegex(UserWarning, "screw_pitch_mm.* source is 'published"):
                    config = load_config(overrides=[override])
            else:
                config = load_config(overrides=[override] if override else [])
            self.assertAlmostEqual(lc2_drive(config, (self.subs["S1"],))[0], s1, places=6, msg=override)
            self.assertAlmostEqual(lc2_drive(config, ())[0] / lc2_drive(config, (self.subs["S1"],))[0], 3 / 0.9, places=9)
        self.assertEqual(lc2_drive(self.config, ())[0], 6800)  # unedited derivation: the YAML force exactly
        with self.assertWarnsRegex(UserWarning, "z_ball_nut.* source is 'published"):
            nut = load_config(overrides=[OLD_RATE, "bought_parts:z_ball_nut.static_axial_rating_N.value=4000"])
        f7 = self.option(2, ("S1", "S3", "S4"), config=nut)["function"]["checks"][F7]
        self.assertAlmostEqual(f7["result"]["value"], 4000 / S1_TORQUE_FORCE, places=9)

    def test_the_drive_check_plunge_force_is_the_lc1_force(self):
        base = self.winner["information"]["z_drive_force_capacity"]["inputs"]
        raised = self.option(2, ("S1", "S3", "S4"), config=load_config(
            overrides=[OLD_RATE, "requirements:load_cases.LC1_cutting_force.force_N.value=400"]))["information"]["z_drive_force_capacity"]["inputs"]
        self.assertEqual((base["plunge_force"]["value"], raised["plunge_force"]["value"]), (200, 400))
        self.assertAlmostEqual(raised["required"]["value"] - base["required"]["value"], 200, places=9)

    def test_a_material_change_uses_the_bar_price_and_a_sourced_lead_bound(self):
        alloy = ["requirements:made_parts.parts.ZXVerbinder.material=EN AW-6061"]
        with self.assertRaisesRegex(ValueError, "add elastic_modulus_MPa, yield_strength_MPa, density_g_cm3 for EN AW-6061"):
            self.option(2, ("S1", "S3", "S4"), config=load_config(overrides=alloy))
        props = [f"requirements:material_properties.EN AW-6061.{k}={v}" for k, v in
                 (("elastic_modulus_MPa", 70000), ("yield_strength_MPa", 240), ("density_g_cm3", 2.70))]
        report = self.option(2, ("S1", "S3", "S4"), config=load_config(overrides=alloy + props))
        self.assertIn("bar price used for a cut-to-size blank", report["cost"]["checks"]["C1_changed_part_cost"]["reason"])
        self.assertEqual(statuses(report)["G11_NP1_lead"], PASS)
        steel = ["requirements:made_parts.parts.ZXVerbinder.material=S235 steel"] + [p.replace("EN AW-6061", "S235 steel") for p in props]
        g11 = self.option(2, ("S1", "S3", "S4"), config=load_config(overrides=steel))["fit"]["checks"]["G11_NP1_lead"]
        self.assertEqual(g11["status"], FAIL)
        self.assertIn("No sourced lead bound for S235 steel", g11["reason"])

    def test_each_substitution_fixes_only_its_own_check(self):
        s1, s13, s14 = self.option(2, ("S1",)), self.option(2, ("S1", "S3")), self.option(2, ("S1", "S4"))
        self.assertEqual((s1["verdict"], statuses(s1)[F7], statuses(s1)[G10]), ("REJECT", PASS, FAIL))
        for report, joint in ((s13, "motor_m5_1"), (s14, "rear_clamp_m8_1")):  # the joint not fixed engages 0 mm
            self.assertEqual((report["verdict"], [k for k, s in statuses(report).items() if s == FAIL]), ("REJECT", [G10]))
            self.assertEqual(report["fit"]["checks"][G10]["inputs"][f"{joint}.engagement"]["value"], 0.0)
        self.assertIn("G10", {f["check"] for f in s1["compliance"]})

    def test_an_undeclared_change_fails_g0_and_every_dependent_unchanged_check(self):
        (spindle,) = [p for p in self.cache.facts["parts"] if p["name"] == "Spindle GDZ-23"]
        moved = {**spindle, "bounds": [b + (1.0 if i in (0, 3) else 0.0) for i, b in enumerate(spindle["bounds"])]}
        report = self.option(2, ("S1", "S3", "S4"), extra={spindle["index"]: moved})  # spindle moved 1 mm in X, not declared
        g0 = report["fit"]["checks"]["G0_change_confined_to_rule"]
        self.assertEqual((g0["status"], g0["undeclared_changed_parts"]), (FAIL, ["Spindle GDZ-23"]))
        self.assertTrue({"F5_LC1_assembly_yield", "F6_LC2_assembly_yield", "G6_IF3_z_travel", "G12_NP2_metric_threads"}
                        <= failed(report))
        self.assertEqual(report["verdict"], "REJECT")

    def test_a_substitution_without_a_reason_for_a_check_cannot_claim_unchanged(self):
        subs = copy.deepcopy(self.subs)
        del subs["S1"]["unchanged_proofs"]["F5"]
        report = self.option(2, ("S1", "S3", "S4"), subs=subs)
        self.assertEqual(statuses(report)["F5_LC1_assembly_yield"], FAIL)  # not demonstrable without a reason
        self.assertEqual((report["verdict"], [k for k, s in statuses(report).items() if s == FAIL]),
                         ("REJECT", ["F5_LC1_assembly_yield"]))


class TestLoadPath(unittest.TestCase):
    def test_load_path_reproduces_the_old_values(self):
        result = analyze(cache_module.load(), load_config())["directions"]
        old = {"+X": {"moving_plate": 0.0014802269669510555, "fixed_guide_plate": 0.0005620367667385752,
                      "zxverbinder_pair": 0.0006635418835897888},
               "+Y": {"moving_plate": 0.06945594985676064, "fixed_guide_plate": 0.09211503220785149}}
        for direction, parts in old.items():
            for part, deflection in parts.items():
                self.assertAlmostEqual(result[direction]["parts"][part]["deflection"]["result"]["value"], deflection, places=12)
        self.assertEqual(result["+X"]["stiffness_ranking"], ["moving_plate", "zxverbinder_pair", "fixed_guide_plate"])
        self.assertEqual(result["-Y"]["stiffness_ranking"], ["fixed_guide_plate", "moving_plate"])
        self.assertAlmostEqual(result["+X"]["parts"]["moving_plate"]["bending_stress"]["result"]["value"], 0.7281938715022775, places=12)
        self.assertEqual(result["+X"]["reactions"]["x_nut.force_x"]["result"]["value"], -200)
        self.assertAlmostEqual(result["+X"]["reactions"]["x_carriages.couple_y"]["result"]["value"], 48640.0, places=6)
        for direction in result.values():
            self.assertTrue(all(r["status"] == PASS for r in direction["equilibrium"].values()))

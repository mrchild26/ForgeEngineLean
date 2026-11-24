import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from src import cache
from src.config import load_config
from src.cost_eval import plate_cost
from src.geometry import bounds, same_solid

# Old repo results/original.json, manufacturing.<part> in EUR/assembly (all occurrences).
OLD_PART_COSTS = {"MotorHalterPlatteIsel": 48.064818, "MotorHalter1": 168.779523, "MotorHalter2": 188.965871,
                  "ZFuehrungsHalter": 43.954753, "FestLagerHalterIsel": 25.236107, "LosLagerHalterIsel": 41.238549,
                  "FestLagerBlock": 41.641213, "SensorPlatteZ": 8.239146, "Nema23HalterFuss": 20.085200,
                  "ZXVerbinder": 84.977976}


class TestAssemblyCache(unittest.TestCase):
    """Needs the cache (built on first use, about 1 min); later loads take well under a second."""

    @classmethod
    def setUpClass(cls):
        cls.cache = cache.load()
        cls.config = load_config(overrides=["cost_model:removal_rate_mm3_min=1000"])  # old repo's costs use the old rate

    def test_warm_load_is_fast(self):
        started = time.perf_counter()
        warm = cache.load()
        self.assertFalse(warm.built)
        self.assertLess(time.perf_counter() - started, 5.0)

    def test_facts_reproduce_the_old_measurements(self):
        facts = self.cache.facts
        self.assertAlmostEqual(facts["rail_coverage"]["coverage_mm"], 138.6, places=6)
        gaps = [screw["gap_to_plate_mm"] for screw in facts["rear_clamp_m8"]]
        self.assertEqual(len(gaps), 4)
        for gap in gaps:
            self.assertAlmostEqual(gap, 12.0, places=6)
        for screw in facts["rear_clamp_m8"]:  # head seat 8 mm below the head top; 92 mm to the plate face
            self.assertAlmostEqual(screw["screw_ymax"] - screw["head_seat_y"], 8.0, places=6)
            self.assertAlmostEqual(screw["head_seat_y"] - screw["plate_ymax"], 92.0, places=6)
        m5 = [j for j in facts["threaded_joints"] if j["joint"] == "motor_m5"]
        self.assertEqual(len(m5), 4)
        for joint in m5:  # flange 5 + standoff 50 to the 4.2 mm holes in FestLagerBlock, 19.5 mm deep; tip 5 mm short
            self.assertEqual((joint["nominal_d"], joint["thread_part"]), (5.0, "FestLagerBlock"))
            self.assertAlmostEqual(joint["thread_near"] - joint["head_seat"], 55.0, places=5)
            self.assertAlmostEqual(joint["thread_far"] - joint["thread_near"], 19.5, places=6)
            tip = next(p for p in facts["parts"] if p["index"] == joint["index"])["bounds"][5]
            self.assertAlmostEqual(joint["thread_near"] - tip, 5.0, places=5)
        self.assertEqual(sum(j["joint"] == "rear_clamp_m8" for j in facts["threaded_joints"]), 4)
        motor = facts["z_motor"]
        for key, expected in (("flange_face_z", -203.0), ("rear_z", -279.0), ("shaft_tip_z", -187.07374),
                              ("shaft_diameter_mm", 6.35), ("axis_x", 3.889533), ("axis_y", 57.163776)):
            self.assertAlmostEqual(motor[key], expected, places=5, msg=key)
        nuts = self.cache.parts_named(cache.Z_NUT)
        self.assertEqual(len(nuts), 1)
        self.assertEqual(nuts[0]["spans_sorted_mm"], [24.0, 24.0, 37.5])
        bores = [p["z_bore_max_mm"] for name in ("MotorHalter1", "MotorHalter2") for p in self.cache.parts_named(name)]
        self.assertEqual(len(bores), 4)
        for bore in bores:
            self.assertAlmostEqual(bore, 80.0, places=6)
        moving = facts["z_moving_set"]
        self.assertEqual(len(moving["indices"]), 46)
        self.assertAlmostEqual(facts["native_extremes"]["z"]["max"]["value"], 233.874339, places=5)

    def test_facts_reproduce_the_original_manufacturing_cost(self):
        total = 0.0
        for spec in self.config.requirements["made_parts"]["parts"]:
            occurrences = self.cache.occurrences(spec["part_id"])
            self.assertEqual(len(occurrences), spec["quantity"], spec["part_id"])
            part_total = sum(plate_cost(p["spans_sorted_mm"], p["volume_mm3"], p["setups"], spec["material"], self.config)["total"]
                             for p in occurrences)
            self.assertAlmostEqual(part_total, OLD_PART_COSTS[spec["part_id"]], places=6, msg=spec["part_id"])
            total += part_total
        self.assertAlmostEqual(total, 671.183158, places=6)

    def test_facing_allowance_moves_a_20_mm_part_to_25_mm_plate(self):
        (part, *_) = self.cache.occurrences("ZXVerbinder")
        self.assertAlmostEqual(part["spans_sorted_mm"][0], 20.0, places=6)
        default = plate_cost(part["spans_sorted_mm"], part["volume_mm3"], part["setups"], "EN AW-5083", self.config)
        faced = plate_cost(part["spans_sorted_mm"], part["volume_mm3"], part["setups"], "EN AW-5083",
                           load_config(overrides=["cost_model:removal_rate_mm3_min=1000", "cost_model:facing_allowance_mm=1.0",
                                                  "cost_model:extra_setups_per_part=1"]))
        self.assertEqual((default["stock_thickness"], faced["stock_thickness"]), (20, 25))
        self.assertEqual(faced["setups"], default["setups"] + 1)
        self.assertGreater(faced["total"], default["total"])

    def test_cached_connector_solids_match_their_facts(self):
        self.assertEqual(len(self.cache.connectors), 2)
        for shape, index in zip(self.cache.connectors, self.cache.facts["connector_indices"]):
            for a, b in zip(bounds(shape), self.cache.facts["parts"][index]["bounds"]):
                self.assertAlmostEqual(a, b, places=5)

    @unittest.skipUnless(os.environ.get("FORGE_SLOW") == "1", "slow: rebuilds the cache from the 67 MB STEP")
    def test_slow_fresh_build_matches_the_cache(self):
        with TemporaryDirectory() as directory:
            fresh = cache.load(root=Path(directory))
            self.assertTrue(fresh.built)
            strip = lambda facts: {k: v for k, v in facts.items() if k != "build_seconds"}  # noqa: E731
            self.assertEqual(json.dumps(strip(fresh.facts), sort_keys=True), json.dumps(strip(self.cache.facts), sort_keys=True))
            for a, b in zip(fresh.connectors, self.cache.connectors):
                self.assertTrue(same_solid(a, b))

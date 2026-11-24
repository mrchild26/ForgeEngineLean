import unittest

from src import cache as cache_module
from src.config import load_config
from src.cost_eval import plate_cost
from tools.thickness_screen import saving_bound, thinner_savings


class TestThicknessScreen(unittest.TestCase):
    def test_saving_uses_the_cost_model_spans_and_respects_the_bound(self):
        cache, config = cache_module.load(), load_config()
        (plate,) = cache.parts_named("MotorHalterPlatteIsel")
        box_thickness = min(plate["bounds"][i + 3] - plate["bounds"][i] for i in range(3))
        self.assertGreater(box_thickness, 20.0)  # 20.000000000000057: the raw box must not pick the 25 mm plate
        base = plate_cost(plate["spans_sorted_mm"], plate["volume_mm3"], plate["setups"], "EN AW-5083", config)
        self.assertEqual(base["stock_thickness"], 20)
        savings = dict(thinner_savings(plate, 1, "EN AW-5083", config, [3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30]))
        self.assertEqual(sorted(savings), [12, 15])
        for thinner, saving in savings.items():  # the plate fills its 20 mm stock, so the simple thickness-ratio bound applies too
            self.assertLessEqual(saving, (20 - thinner) / 20 * (base["material"] + base["milling"]) + 0.01)
            self.assertLessEqual(saving, saving_bound(base, 130.0, 137.0, thinner) + 0.01)
        self.assertAlmostEqual(savings[15], 1.36, places=2)  # independent hand value
        self.assertAlmostEqual(savings[12], 2.17, places=2)


class TestProcessReview(unittest.TestCase):
    def test_route_classification(self):
        from tools.process_review import best, classify, made_shapes, routes
        cache, config = cache_module.load(), load_config()
        shapes = made_shapes(cache, config)
        plate = classify(shapes["SensorPlatteZ"])  # 3 mm plate, all features through the thickness
        self.assertTrue(plate["profile"])
        self.assertEqual((plate["side"], plate["tapped"], plate["tight"]), ([], 0, 0))
        costs, today = routes(plate, "EN AW-5083", config)
        facts = cache.occurrences("SensorPlatteZ")[0]  # route A without hole time is the grader's cost model
        self.assertAlmostEqual(today["total"], plate_cost(facts["spans_sorted_mm"], facts["volume_mm3"], facts["setups"],
                                                          "EN AW-5083", config)["total"], places=6)
        self.assertEqual(best(costs)[0], "D")
        connector = classify(cache.connectors[0])  # Y bores across a 20 mm plate: side features, above the laser limit
        self.assertEqual((connector["profile"], connector["side"]), (False, [1]))
        costs, _ = routes(connector, "EN AW-5083", config)
        self.assertIsNone(costs["C"])
        self.assertEqual(best(costs)[0], "A")
        clamp = classify(shapes["MotorHalter1"])  # the open IF1 bore counts as a tight feature
        self.assertEqual(clamp["tight"], 1)

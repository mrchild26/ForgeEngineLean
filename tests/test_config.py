import copy
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
import warnings

from src.config import (DEFAULTS, SCHEMA, Config, check_rule, load_config, material_properties, override_lines, read_yaml,
                        validate)


class TestConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()

    def test_thresholds_are_parsed_from_the_requirement_text(self):
        self.assertAlmostEqual(self.config.deflection_limit, 1.10)
        self.assertEqual(self.config.thread_engagement_ratio, 1.5)
        self.assertEqual(self.config.lead_limit_percent, 0.1)
        changed = copy.deepcopy(self.config.requirements)
        rule = changed["limits"]["tool_tip_deflection_LC1"]
        rule["rule"] = rule["rule"].replace("110%", "105%")
        self.assertAlmostEqual(Config(changed, self.config.rates, self.config.cost_model, self.config.rule).deflection_limit, 1.05)

    def test_lot_size_comes_from_the_requirements_and_warns_on_a_rates_mismatch(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            self.assertEqual(self.config.lot_size, 10)  # both files say 10: no warning
        rates = {**self.config.rates, "production": {**self.config.rates["production"], "lot_size": 25}}
        mismatch = Config(self.config.requirements, rates, self.config.cost_model, self.config.rule)
        with self.assertWarnsRegex(UserWarning, "lot_size 25 differs .* using 10"):
            self.assertEqual(mismatch.lot_size, 10)

    def test_rules_are_validated_against_the_schema(self):
        rule = self.config.rule
        self.assertEqual(rule["parameter"]["values"], list(range(1, 11)))
        self.assertEqual(rule["protected_features"]["bolt_seat_radius_mm"], 6.0)
        self.assertEqual([s["id"] for s in self.config.substitutions], ["S1", "S3", "S4"])
        schemas = read_yaml(SCHEMA)
        trim = read_yaml(DEFAULTS["rules"] / "zxverbinder_trim.yaml")
        subs = read_yaml(DEFAULTS["rules"] / "bought_part_substitutions.yaml")
        for raw, path, value, message in (
                (trim, ("operation",), "taper", "not one of"),
                (trim, ("parameter", "values"), [1, 1], "unique"),
                (trim, ("parameter", "values"), [0], "below"),
                (trim, ("parameter", "unit"), "inch", "not one of"),
                (trim, ("attribution", "hardware_license"), 3, "expected string"),
                (trim, ("unchanged_proofs", "F5"), 5, "expected string"),
                (subs, ("substitutions", 0, "price_to", "amount"), "cheap", "expected number"),
                (subs, ("substitutions", 0, "price_to", "status"), "guessed", "not one of"),
                (subs, ("substitutions", 1, "price_from", "vat"), "maybe", "not one of"),
                (subs, ("substitutions", 1, "price_from", "per_quantity"), 0, "below"),
                (subs, ("substitutions", 1, "geometry", "type"), "cube", "not one of"),
                (subs, ("substitutions", 0, "conversion", "rate"), 0, "below")):
            bad = copy.deepcopy(raw)
            target = bad
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, message):
                check_rule(bad, schemas)
        for raw, key in ((trim, "attribution"), (subs, "substitutions")):
            missing = copy.deepcopy(raw)
            del missing[key]
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, f"missing \\['{key}'\\]"):
                validate(missing, schemas[raw["rule_type"]])
        no_price = copy.deepcopy(subs)
        del no_price["substitutions"][1]["price_from"]
        with self.assertRaisesRegex(ValueError, "missing \\['price_from'\\]"):
            check_rule(no_price, schemas)
        no_rate = copy.deepcopy(subs)
        del no_rate["substitutions"][1]["price_to"]["vat_rate"]  # S3 M8 x 110: shown incl. VAT
        with self.assertRaisesRegex(ValueError, "needs vat_rate"):
            check_rule(no_rate, schemas)

    def test_overrides_change_values_in_memory_only_and_are_recorded(self):
        config = load_config(overrides=["cost_model:removal_rate_mm3_min=20000"])
        self.assertEqual(config.cost_model["removal_rate_mm3_min"], 20000)
        self.assertEqual(config.overrides, ({"file": "cost_model", "key": "removal_rate_mm3_min", "from": 50000, "to": 20000},))
        self.assertEqual(read_yaml(DEFAULTS["cost_model"])["removal_rate_mm3_min"], 50000)  # never written back
        with self.assertWarnsRegex(UserWarning, "IF3_z_travel.* source is 'published"):
            listed = load_config(overrides=["requirements:load_cases.LC1_cutting_force.force_N.value=400",
                                            "requirements:interfaces_that_must_not_change.IF3_z_travel.travel_mm.value=150"])
        self.assertEqual(listed.requirements["load_cases"][0]["force_N"]["value"], 400)  # list items addressed by id
        self.assertEqual(listed.requirements["interfaces_that_must_not_change"][2]["travel_mm"]["value"], 150)
        self.assertEqual([(o["key"], o["from"], o["to"]) for o in listed.overrides],
                         [("load_cases.LC1_cutting_force.force_N.value", 200, 400),
                          ("interfaces_that_must_not_change.IF3_z_travel.travel_mm.value", 80, 150)])
        with self.assertWarnsRegex(UserWarning, "source is 'task_rule'"):
            changed = load_config(overrides=["requirements:production.lot_size=20"])
        self.assertEqual(changed.requirements["production"]["lot_size"]["value"], 20)

    def test_an_unknown_or_mistyped_override_raises(self):
        for text, message in (("cost_model:removal_rate=1", "unknown key"), ("costmodel:removal_rate_mm3_min=1", "expected"),
                              ("cost_model:removal_rate_mm3_min", "expected"), ("cost_model:removal_rate_mm3_min=fast", "type"),
                              ("requirements:load_cases.LC9.force_N=1", "unknown key")):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, message):
                load_config(overrides=[text])

    def test_a_numeric_value_wins_over_the_rule_text_and_a_broken_text_names_the_key(self):
        config = load_config(overrides=["requirements:limits.tool_tip_deflection_LC1.value=1.05",
                                        "requirements:limits.thread_engagement.value=2",
                                        "requirements:non_physical_requirements.market.rules.NP1_lead_content.value=0.05"])
        self.assertEqual((config.deflection_limit, config.thread_engagement_ratio, config.lead_limit_percent), (1.05, 2.0, 0.05))
        self.assertEqual(override_lines(config)[0], "Override (in memory only): requirements:limits.tool_tip_deflection_LC1.value "
                                                    "1.1 (from rule text) -> 1.05")
        reworded = load_config(overrides=["requirements:limits.thread_engagement.rule=At least one and a half diameters."])
        with self.assertRaisesRegex(ValueError, 'set a number with --set "requirements:limits.thread_engagement.value=<number>"'):
            reworded.thread_engagement_ratio

    def test_keys_with_spaces_and_a_new_alloy_can_be_set_in_memory(self):
        config = load_config(overrides=["rates:materials.EN AW-5083 plate.price_eur_kg=6",
                                        "requirements:material_properties.EN AW-6061.density_g_cm3=2.7"])
        self.assertEqual(config.rates["materials"]["EN AW-5083 plate"]["price_eur_kg"], 6)
        self.assertEqual(config.requirements["material_properties"]["EN AW-6061"]["density_g_cm3"]["value"], 2.7)
        with self.assertRaisesRegex(ValueError, "add elastic_modulus_MPa, yield_strength_MPa for EN AW-6061 under material_properties"):
            material_properties(config.requirements, "EN AW-6061")
        with self.assertRaisesRegex(ValueError, "unknown key"):  # creation is limited to material_properties.<alloy>.<key>
            load_config(overrides=["requirements:limits.new_limit.value=1"])

    def test_the_nut_rating_is_bought_part_data(self):
        with self.assertWarnsRegex(UserWarning, "z_ball_nut.* source is 'published"):
            config = load_config(overrides=["bought_parts:z_ball_nut.static_axial_rating_N.value=4000"])
        self.assertEqual(config.z_ball_nut["static_axial_rating_N"]["value"], 4000)
        self.assertEqual(load_config().z_ball_nut["static_axial_rating_N"]["value"], 3000)

    def test_a_substitution_must_start_from_the_yaml_value(self):
        with TemporaryDirectory() as directory:
            for name in ("zxverbinder_trim.yaml", "bought_part_substitutions.yaml", "bought_parts.yaml"):
                shutil.copy(DEFAULTS["rules"] / name, directory)
            path = Path(directory) / "bought_part_substitutions.yaml"
            path.write_text(path.read_text(encoding="utf-8").replace("from: 3\n", "from: 2.5\n"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "motor_torque_Nm is 3, not the declared 'from' value 2.5"):
                load_config(rules=directory)

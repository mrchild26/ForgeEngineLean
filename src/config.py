"""Read the task files at runtime, validate the design rule and parse thresholds written as rule text."""

import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = {"requirements": ROOT / "requirements" / "subassembly.yaml", "rates": ROOT / "requirements" / "rates.yaml",
            "cost_model": ROOT / "rules" / "cost_model.yaml", "rules": ROOT / "rules"}
EVIDENCE = ROOT / "evidence" / "z_travel_sweep.yaml"  # measured once by the old repo; carried by G6
SCHEMA = ROOT / "rules" / "schema.yaml"
TYPES = {"string": str, "integer": int, "number": (int, float), "list": list, "map": dict}
GEOMETRY_FIELDS = {"motor_envelope": ("body_mm", "shaft_diameter_mm", "shaft_length_mm"),
                   "socket_head_screw": ("shank_diameter_mm", "length_mm", "head_diameter_mm", "head_height_mm")}


def read_yaml(path):
    with Path(path).open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def validate(value, schema, where="rule"):
    """Check a value against the small schema language of rules/schema.yaml."""
    kind = TYPES[schema["type"]]
    if not isinstance(value, kind) or (schema["type"] in ("integer", "number") and isinstance(value, bool)):
        raise ValueError(f"{where}: expected {schema['type']}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{where}: {value!r} is not one of {schema['enum']}")
    if "minimum" in schema and value < schema["minimum"]:
        raise ValueError(f"{where}: {value} is below {schema['minimum']}")
    if schema["type"] == "list":
        if len(value) < schema.get("min_items", 0):
            raise ValueError(f"{where}: needs at least {schema['min_items']} items")
        if schema.get("unique") and len(set(map(repr, value))) != len(value):
            raise ValueError(f"{where}: items must be unique")
        for index, item in enumerate(value):
            validate(item, schema["items"], f"{where}[{index}]")
    if schema["type"] == "map":
        if "values" in schema:  # free keys, e.g. check id -> proof text
            for key, item in value.items():
                validate(item, schema["values"], f"{where}.{key}")
            return
        missing = [key for key in schema.get("required", ()) if key not in value]
        unknown = [key for key in value if key not in schema.get("fields", {})]
        if missing or unknown:
            raise ValueError(f"{where}: missing {missing}, unknown {unknown}")
        for key, item in value.items():
            validate(item, schema["fields"][key], f"{where}.{key}")


def check_rule(rule, schemas, where="rule"):
    """Validate one rule against the schema of its rule_type; return it with sorted parameter values."""
    kind = rule.get("rule_type")
    if kind not in schemas:
        raise ValueError(f"{where}: unknown rule_type {kind!r}")
    validate(rule, schemas[kind], where)
    if kind == "design_option":
        return {**rule, "parameter": {**rule["parameter"], "values": sorted(rule["parameter"]["values"])}}
    for sub in rule["substitutions"]:
        missing = [f for f in GEOMETRY_FIELDS[sub["geometry"]["type"]] if f not in sub["geometry"]]
        if missing:
            raise ValueError(f"{where}: {sub['id']} geometry needs {missing}")
        if sub["currency"] != "EUR" and "conversion" not in sub:
            raise ValueError(f"{where}: {sub['id']} needs a conversion to EUR")
        if any(sub[side]["vat"] == "included" and "vat_rate" not in sub[side] for side in ("price_from", "price_to")):
            raise ValueError(f"{where}: {sub['id']} a price including VAT needs vat_rate")
    return rule


def load_rules(directory=DEFAULTS["rules"], schema_path=SCHEMA):
    """Every YAML file in the directory with a rule_type key, validated, in file-name order."""
    schemas = read_yaml(schema_path)
    documents = {p.name: read_yaml(p) for p in sorted(Path(directory).glob("*.yaml"))}
    return tuple(check_rule(doc, schemas, name) for name, doc in documents.items()
                 if isinstance(doc, dict) and "rule_type" in doc)


def yaml_value(data, path):
    """Value at a dotted path; a list step selects the item whose id starts with the key (LC2_crash, IF3_z_travel)."""
    node = data
    for key in path.split("."):
        if isinstance(node, list):
            matches = [item for item in node if str(item.get("id", "")).startswith(key)]
            if len(matches) != 1:
                raise KeyError(path)
            node = matches[0]
        else:
            node = node[key]
    return node["value"] if isinstance(node, dict) and "value" in node else node


def number_in(text, pattern, label):
    match = re.search(pattern, text)
    if match is None:
        raise ValueError(f"Cannot read the {label} threshold from: {text!r}")
    return float(match.group(1))


TEXT_THRESHOLDS = {  # requirements key: (pattern in the rule text, divisor, label)
    "limits.tool_tip_deflection_LC1": (r"(\d+(?:\.\d+)?)\s*%", 100, "deflection"),
    "limits.thread_engagement": (r"(\d+(?:\.\d+)?)\s*times", 1, "thread engagement"),
    "non_physical_requirements.market.rules.NP1_lead_content": (r"(\d+(?:\.\d+)?)\s*%", 1, "lead")}


def threshold(item, key):
    """A numeric 'value' key wins over the rule text; the error names the key to set."""
    pattern, divisor, label = TEXT_THRESHOLDS[key]
    if isinstance(item.get("value"), (int, float)):
        return float(item["value"])
    try:
        return number_in(item["rule"], pattern, label) / divisor
    except ValueError:
        raise ValueError(f"Cannot read the {label} threshold from the rule text {item['rule']!r}; set a number with "
                         f"--set \"requirements:{key}.value=<number>\"") from None


MATERIAL_KEYS = ("elastic_modulus_MPa", "yield_strength_MPa", "density_g_cm3")


def material_properties(requirements, alloy):
    """material_properties[alloy] with all three values, or a clear error naming what to add."""
    props = requirements["material_properties"].get(alloy) or {}
    missing = [k for k in MATERIAL_KEYS if k not in props]
    if missing:
        raise ValueError(f"Material {alloy!r}: add {', '.join(missing)} for {alloy} under material_properties, e.g. "
                         f"--set \"requirements:material_properties.{alloy}.{missing[0]}=<number>\"")
    return props


PROTECTED_SOURCES = ("published", "measured", "task_rule")
CREATABLE = "requirements:material_properties."  # --set may create keys here (a new alloy for a live change)


def apply_override(documents, text):
    """Apply one '<file>:<dotted.key>=<value>' override in memory; return its record. Unknown file or key raises.

    A key that holds {value: ..., source: ...} sets its value. The new value must have the same kind as the old one.
    """
    target, sep, raw = text.partition("=")
    name, colon, path = target.partition(":")
    if not sep or not colon or name not in documents:
        raise ValueError(f"Override {text!r}: expected <file>:<dotted.key>=<value> with file in {sorted(documents)}")
    new = yaml.safe_load(raw)
    *parents, last = path.split(".")
    node = documents[name]
    create = target.startswith(CREATABLE) and len(parents) == 2  # material_properties.<alloy>.<property>
    try:
        for key in parents:
            if create and isinstance(node, dict) and key not in node:
                node[key] = {}
            node = next(i for i in node if str(i.get("id", i.get("part_id", ""))).startswith(key)) if isinstance(node, list) else node[key]
        if (create or (last == "value" and "rule" in node)) and last not in node:  # new alloy value or numeric threshold
            node[last] = {"value": None, "source": "override"} if create else None
        holder, key = (node[last], "value") if isinstance(node[last], dict) and "value" in node[last] else (node, last)
        old = holder[key]
    except (KeyError, TypeError, AttributeError, StopIteration):
        raise ValueError(f"Override {text!r}: unknown key {path!r} in {name}") from None
    number = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731
    if old is None and not number(new):
        raise ValueError(f"Override {text!r}: {path} needs a number")
    if old is not None and (number(old) != number(new) or (not number(old) and type(old) is not type(new))):
        raise ValueError(f"Override {text!r}: {path} is {old!r}; the new value {new!r} has a different type")
    source = (holder if holder is not node else node).get("source", "") if isinstance(node, dict) else ""
    if str(source).startswith(PROTECTED_SOURCES):
        warnings.warn(f"Override {text!r} changes a value whose source is {source!r} (analysis only)", stacklevel=2)
    record = {"file": name, "key": path, "from": old, "to": new}
    parent = path.rsplit(".", 1)[0]
    if old is None and name == "requirements" and parent in TEXT_THRESHOLDS:  # report the effective threshold it replaces
        record.update({"from": threshold(node, parent), "from_note": "from rule text"})
    elif old is None:
        record["from_note"] = "new key"
    holder[key] = new
    return record


def price_warnings(substitutions):
    """One warning line per substitution price whose source status is 'unconfirmed'."""
    return [f"WARNING: {s['id']} {side} = {s[side]['amount']} {s['currency']} per {s[side]['per_quantity']} is unconfirmed: "
            f"{s[side].get('note', '')}" for s in substitutions for side in ("price_from", "price_to")
            if s[side]["status"] == "unconfirmed"]


@dataclass(frozen=True)
class Config:
    requirements: dict
    rates: dict
    cost_model: dict
    rule: dict  # the design-option rule (the graders implement symmetric_end_trim of ZXVerbinder)
    substitutions: tuple = ()  # bought-part substitution entries of every substitution rule file
    overrides: tuple = ()  # in-memory --set overrides applied to the files above (records of apply_override)
    z_travel: dict = None  # evidence/z_travel_sweep.yaml
    bought_parts: dict = None  # rules/bought_parts.yaml: data of unchanged bought parts the graders use (Z ball nut)

    def substitution(self, sub_id):
        return next(s for s in self.substitutions if s["id"] == sub_id)

    @property
    def deflection_limit(self):
        """'... not more than 110% of the deflection ...' -> 1.10, or limits.tool_tip_deflection_LC1.value (a ratio)"""
        return threshold(self.requirements["limits"]["tool_tip_deflection_LC1"], "limits.tool_tip_deflection_LC1")

    @property
    def thread_engagement_ratio(self):
        """'... must be 1.5 times the thread diameter ...' -> 1.5, or limits.thread_engagement.value"""
        return threshold(self.requirements["limits"]["thread_engagement"], "limits.thread_engagement")

    @property
    def lead_limit_percent(self):
        """NP1: '... 0.1% of lead ...' -> 0.1, or the rule's value (% mass)"""
        rules = {rule["id"]: rule for rule in self.requirements["non_physical_requirements"]["market"]["rules"]}
        return threshold(rules["NP1_lead_content"], "non_physical_requirements.market.rules.NP1_lead_content")

    @property
    def z_ball_nut(self):
        return self.bought_parts["z_ball_nut"]

    @property
    def lot_size(self):
        """subassembly.yaml production.lot_size is a task_rule; rates.yaml repeats it for convenience."""
        lot = self.requirements["production"]["lot_size"]["value"]
        rates_lot = self.rates.get("production", {}).get("lot_size")
        if rates_lot is not None and rates_lot != lot:
            warnings.warn(f"rates.yaml lot_size {rates_lot} differs from subassembly.yaml lot_size {lot} "
                          f"(task_rule); using {lot}", stacklevel=2)
        return lot


def load_config(requirements=None, rates=None, cost_model=None, rules=None, overrides=()):
    """Read every input file now, so a changed requirement takes effect on the next run.

    overrides: '<file>:<dotted.key>=<value>' strings (file = requirements, rates, cost_model or bought_parts), applied
    in memory only.
    """
    paths = {key: Path(value) if value else DEFAULTS[key] for key, value in
             (("requirements", requirements), ("rates", rates), ("cost_model", cost_model), ("rules", rules))}
    documents = {key: read_yaml(paths[key]) for key in ("requirements", "rates", "cost_model")}
    documents["bought_parts"] = read_yaml(paths["rules"] / "bought_parts.yaml")
    applied = tuple(apply_override(documents, text) for text in overrides or ())
    loaded = load_rules(paths["rules"])
    designs = [r for r in loaded if r["rule_type"] == "design_option"]
    if len(designs) != 1 or (designs[0]["part_id"], designs[0]["operation"]) != ("ZXVerbinder", "symmetric_end_trim"):
        raise ValueError("The graders implement exactly one design-option rule: symmetric_end_trim of ZXVerbinder")
    substitutions = tuple(s for r in loaded if r["rule_type"] == "bought_part_substitution" for s in r["substitutions"])
    if len({s["id"] for s in substitutions}) != len(substitutions):
        raise ValueError("Substitution ids must be unique")
    requirements_data = documents["requirements"]
    for sub in substitutions:
        for item in sub["affected_inputs"]:
            if yaml_value(requirements_data, item["path"]) != item["from"]:
                raise ValueError(f"{sub['id']}: {item['path']} is {yaml_value(requirements_data, item['path'])}, "
                                 f"not the declared 'from' value {item['from']}")
    return Config(requirements_data, documents["rates"], documents["cost_model"], designs[0], substitutions, applied,
                  read_yaml(EVIDENCE), documents["bought_parts"])


def override_lines(config):
    return [f"Override (in memory only): {o['file']}:{o['key']} "
            + (f"{o['from']:g} ({o['from_note']})" if o.get("from_note") == "from rule text" else
               f"({o['from_note']})" if o.get("from_note") else repr(o["from"])) + f" -> {o['to']!r}" for o in config.overrides]

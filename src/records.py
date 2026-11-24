"""Calculation records: every graded result carries its formula, inputs with units, result and status."""

import json
from math import isfinite
from operator import ge, gt, le, lt
from pathlib import Path
from tempfile import TemporaryDirectory

PASS, FAIL, UNCHANGED, INFO = "PASS", "FAIL", "UNCHANGED", "INFO"
COMPARISONS = {"<=": le, ">=": ge, "<": lt, ">": gt}
GRADED = {PASS, FAIL, UNCHANGED}


def measured(value, unit):
    return {"value": value, "unit": unit}


def compare(value, operator, limit):
    """PASS/FAIL for a computed value. A value that cannot be computed is not demonstrable: FAIL."""
    if value is None or limit is None:
        return FAIL
    return PASS if COMPARISONS[operator](value, limit) else FAIL


def change_proof(check, changes, checks, conditions=()):
    """Proof for an UNCHANGED record that names every declared change and why it cannot affect the check.

    changes: (change id, {check id: reason}) per declared change (design rule, substitutions). Returns None when a
    change gives no reason for this check: the record must then be computed, or it is not demonstrable (FAIL).
    """
    reasons = []
    for change_id, texts in changes:
        if check not in texts:
            return None
        reasons.append(f"{change_id}: {texts[check]}")
    return {"checks": list(checks), "conditions": list(conditions),
            "text": "G0: only the declared changes differ from the original. " + " ".join(reasons)}


def calculation(formula, inputs, value, limit, unit, *, operator="<=", reason="", proof=None):
    """A graded record. With `proof`, the requirement is UNCHANGED: proven unaffected by the change.

    proof = {"checks": [ids of records that must PASS], "conditions": [records that must PASS], "text": <why the
    requirement cannot be affected>}. A computed value that fails the threshold is FAIL: a proof never hides it.
    """
    if value is not None and compare(value, operator, limit) == FAIL:
        proof = None
    record = {"formula": formula, "inputs": inputs, "result": measured(value, unit),
              "threshold": {"operator": operator, **measured(limit, unit)},
              "status": UNCHANGED if proof else compare(value, operator, limit), "reason": reason}
    if proof:
        record["proof"] = proof
    validate_record(record)
    return record


def value_record(formula, inputs, value, unit, reason=""):
    """An analysis value without a pass threshold (status INFO); graders never use it."""
    record = {"formula": formula, "inputs": inputs, "result": measured(value, unit),
              "threshold": {"operator": "none", "value": None, "unit": unit}, "status": INFO, "reason": reason}
    validate_record(record)
    return record


def validate_record(record):
    """Reject a record without a formula, inputs with units, a consistent status, or a proof for UNCHANGED."""
    if not isinstance(record.get("formula"), str) or not record["formula"].strip():
        raise ValueError("Missing calculation formula")
    if not record.get("inputs"):
        raise ValueError("Missing calculation inputs")
    for field in (record["result"], record["threshold"], *record["inputs"].values()):
        if not field.get("unit") or "value" not in field:
            raise ValueError("Each measurement needs a value and a unit")
        value = field["value"]
        if value is not None and not (isinstance(value, (int, float)) and isfinite(value)):
            raise ValueError("Measurements must be finite numbers or explicitly unknown")
    if any(field["value"] is None for field in record["inputs"].values()):
        raise ValueError("Record only known inputs")
    if record["result"]["unit"] != record["threshold"]["unit"]:
        raise ValueError("Result and threshold units differ")
    if record["status"] == INFO:
        if record["threshold"] != {"operator": "none", "value": None, "unit": record["result"]["unit"]}:
            raise ValueError("An INFO record has no threshold")
        return
    if record["threshold"]["operator"] not in COMPARISONS:
        raise ValueError("Unknown comparison operator")
    if record["status"] == UNCHANGED:
        proof = record.get("proof") or {}
        checks = proof.get("checks")
        if not checks or not all(str(c).strip() for c in checks) or not str(proof.get("text", "")).strip():
            raise ValueError("An UNCHANGED record needs proof checks and text")
        for condition in proof.get("conditions", ()):
            validate_record(condition)
    elif record["status"] != compare(record["result"]["value"], record["threshold"]["operator"],
                                     record["threshold"]["value"]):
        raise ValueError("Calculation status disagrees with the comparison")


def proof_holds(proof, statuses):
    """Every named check PASSes and every proof condition PASSes."""
    return (all(statuses.get(c) == PASS for c in proof["checks"])
            and all(c["status"] == PASS for c in proof.get("conditions", ())))


def grader_summary(grader, records, statuses):
    """The grader's PASS/FAIL: count of FAIL records and UNCHANGED records whose proof does not hold.

    `statuses` maps every check id of the case (all graders) to its status, because a proof may live in another grader.
    """
    failed = sorted(key for key, record in records.items() if record["status"] == FAIL
                    or (record["status"] == UNCHANGED and not proof_holds(record["proof"], statuses)))
    summary = calculation(
        "failed = count(status == FAIL) + count(status == UNCHANGED and proof check != PASS)",
        {"checks": measured(len(records), "count"),
         "unchanged_with_proof": measured(sum(r["status"] == UNCHANGED for r in records.values()), "count")},
        len(failed), 0, "count", reason=f"{grader} grader")
    summary["failed_checks"] = failed
    return summary


def validate_report(report):
    """Validate every record of every grader in a case report."""
    for grader in ("function", "fit", "cost"):
        for record in report[grader]["checks"].values():
            validate_record(record)
            if record["status"] not in GRADED:
                raise ValueError("A grader record must be PASS, FAIL or UNCHANGED")
        validate_record(report[grader]["summary"])


def write_json(path, content):
    """Write atomically so an interrupted run never leaves a partial report."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=path.parent) as staging:
        staged = Path(staging) / path.name
        staged.write_text(json.dumps(content, indent=1, allow_nan=False) + "\n", encoding="utf-8")
        staged.replace(path)

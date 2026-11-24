"""Write EVALS.md from the graded winner (results/best.json), the rule files and the config, so its numbers cannot
drift from the records. Run after bench.py: python tools/write_evals.py"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import ROOT, load_config  # noqa: E402
from src.cost_eval import piece_price  # noqa: E402

METRIC = {  # id: (metric, source of the threshold)
    "F1": ("Tear-out stress at the outer bolt hole, full LC1 force on one bolt", "LC1 force; yield / safety_factor_yield_LC1"),
    "F2": ("Bearing stress of the M6 bolt in the ZXVerbinder", "as F1"),
    "F3": ("Net-section stress beside the outer hole", "as F1"),
    "F4": ("Upper bound of the LC1 tool-tip deflection ratio, case / original (contact + arm)", "limits.tool_tip_deflection_LC1 (110%)"),
    "F5": ("Whole-assembly yield safety factor, LC1 (not modelled)", "safety_factor_yield_LC1; proof G0, G3"),
    "F6": ("Whole-assembly yield safety factor, LC2 (not modelled)", "safety_factor_yield_LC2; proof G0 + F_new <= F_orig"),
    "F7": ("Z ball nut: static rating (rules/bought_parts.yaml) / LC2 force", "safety_factor_yield_LC2 (our interpretation, Appendix)"),
    "G0": ("Changes outside the declared ones, rule-1 conformance, substitution geometry", "ours: basis of every proof"),
    "G1": ("Placed copies of the changed part differ", "task: STEP in the original coordinates"),
    "G2": ("Material added to the changed part (removal only)", "ours: machinable from the original stock"),
    "G3": ("Change of the protected core (holes, bolt seats, ball-nut face)", "IF4/IF5 bolt pattern"),
    "G4": ("Clamp bore deviation from 80 mm", "IF1_spindle_clamp"),
    "G5": ("Moved or missing spindle occurrences", "IF2_spindle_axis"),
    "G6": ("Z travel of the moving set (original sweep, carried while the proof holds)", "IF3_z_travel"),
    "G7": ("Moved or missing X carriages", "IF4_x_axis_carriages"),
    "G8": ("Ball-nut pad area change, nut parts unmoved", "IF5_x_axis_ball_nut"),
    "G9": ("Smallest margin to the envelope box in the YAML frame (tool excluded)", "envelope"),
    "G10": ("Thread engagement of the rear-clamp M8 and motor M5 joints", "limits.thread_engagement"),
    "G11": ("Lead bound of the made-part alloy (EN 573-3)", "NP1_lead_content"),
    "G12": ("Fastener labels without an ISO metric designation", "NP2_metric_threads"),
    "G13": ("Made parts without an approved plate thickness", "NP3_stock_thickness"),
    "G14": ("Padded envelope minus parcel limit", "NP4_parcel_size"),
    "G15": ("Made-part mass change", "NP5_mass"),
    "G16": ("Deviation of made-part quantities", "made_parts"),
    "G17": ("Changed bought parts without reason, both prices and a source", "bought_parts"),
    "C1": ("Cost of the changed part (all occurrences)", "task: cost from the geometry"),
    "C2": ("Manufacturing cost of all made parts", "rates.yaml + rules/cost_model.yaml"),
    "C3": ("Cost change of the subassembly incl. bought parts", "task: the change is less expensive"),
}


def source(price, label):
    """Link to the price page, plus the shop's article number where the URL is not a product page."""
    return f"[{label}]({price['url']})" + (f" (art. {price['article']})" if price.get("article") else "")


def load_case_force(config):
    return next(lc for lc in config.requirements["load_cases"] if lc["id"].startswith("LC2"))["force_N"]["value"]


def number(value):
    if value is None:
        return "–"
    if isinstance(value, int) or float(value).is_integer():
        return f"{value:g}"
    return f"{value:.4g}" if abs(value) < 1000 else f"{value:.2f}"


def table(report, grader):
    rows = ["| ID | Metric | Threshold | Source | Winner |", "|---|---|---|---|---|"]
    for key, rec in sorted(report[grader]["checks"].items(), key=lambda kv: int(kv[0][1:].split("_")[0])):
        short = key.split("_", 1)[0]
        unit = {"count": "", "1": "", "mm^3": "mm³", "mm^2": "mm²"}.get(rec["result"]["unit"], rec["result"]["unit"])
        threshold = f"{rec['threshold']['operator']} {number(rec['threshold']['value'])} {unit}".strip()
        winner = f"{number(rec['result']['value'])} {unit if rec['result']['value'] is not None else ''}".strip()
        rows.append(f"| {short} | {METRIC[short][0]} | {threshold} | {METRIC[short][1]} | {winner} {rec['status']} |")
    return rows


def main():
    report = json.loads((ROOT / "results" / "best.json").read_text(encoding="utf-8"))
    config = load_config()
    checks = {k: r for g in ("function", "fit", "cost") for k, r in report[g]["checks"].items()}
    f7, c1, c3 = checks["F7_z_ball_nut_capacity"]["inputs"], checks["C1_changed_part_cost"]["inputs"], checks["C3_cost_delta"]["inputs"]
    occ = {k.split(".", 1)[1]: v["value"] for k, v in c1.items() if k.startswith("occurrence_1.")}
    rate, hourly = c1["removal_rate"]["value"], c1["machine_rate"]["value"] + c1["labour_rate"]["value"]
    lines = [
        "# EVALS", "",
        "Graders for one design change (`src/function_eval.py`, `src/fit_eval.py`, `src/cost_eval.py`). Each check is a "
        "record with formula, inputs with units, result, threshold and status (`results/<case>.json`). This page is "
        f"written by `tools/write_evals.py` from `results/best.json` (winner `{report['case_id']}`).", "",
        "**Status rules.** PASS/FAIL compare a computed value with its threshold; a computed failing value is always FAIL. "
        "UNCHANGED only for a check that is not computed, with a proof naming checks that must PASS (and computed "
        "conditions); a proof that does not hold counts as FAIL. A grader PASSes with 0 failed checks; ACCEPT = all three "
        "graders PASS; the original is REFERENCE.", "",
        "## Function", *table(report, "function"), "", "## Fit", *table(report, "fit"), "", "## Cost", *table(report, "cost"), "",
        "## Hand check",
        f"- **F7 (winner):** F = F_YAML · s · T/T_YAML = {number(f7['yaml_force']['value'])} · {number(f7['drive_scale']['value'])} · "
        f"{number(f7['motor_torque']['value'])}/{number(f7['yaml_motor_torque']['value'])} = {f7['axial_demand']['value']:.2f} N "
        f"(s = 1: 2·π·{number(f7['yaml_motor_torque']['value'])}·{number(f7['screw_efficiency']['value'])}/"
        f"({number(f7['screw_pitch']['value'])}/1000) = {f7['derived_force']['value']:.2f} N matches the YAML's "
        f"{number(f7['yaml_derived_force']['value'])} N within its rounding; an edited pitch or efficiency sets s); "
        f"{number(f7['catalog_static_axial_rating']['value'])} / {f7['axial_demand']['value']:.2f} = "
        f"{checks['F7_z_ball_nut_capacity']['result']['value']:.3f} ≥ {number(checks['F7_z_ball_nut_capacity']['threshold']['value'])}.",
        f"- **One ZXVerbinder at {rate:g} mm³/min:** stock {occ['stock_length']:g} × {occ['stock_width']:g} × "
        f"{occ['stock_thickness']:g} mm → {occ['stock_mass']:.6f} kg × {c1['price']['value']:.2f} €/kg = {occ['material']:.6f} €; "
        f"chips {occ['chip_volume']:.3f} mm³ ÷ {rate:g} = {occ['milling_time']:.6f} min × {hourly:g} €/h ÷ 60 = "
        f"{occ['milling']:.6f} €; setup {occ['setups']:g} × {c1['setup_time']['value']:g} min × {hourly:g} €/h ÷ 60 ÷ "
        f"{c1['lot_size']['value']:g} = {occ['setup']:.6f} €; chip credit {occ['chip_volume']:.3f} × "
        f"{c1['density']['value']:g}e-6 kg × {c1['chip_price']['value']:.2f} €/kg = {occ['scrap_credit']:.6f} €; "
        f"**total {occ['total']:.6f} €**.", "",
        "## Appendix",
        "**Assumptions and interpretations.** No value in `requirements/*.yaml` is changed. What we interpret or add:", "",
        "| Item | Interpretation | Why |", "|---|---|---|",
        "| F7 | The nut's static rating is its yield: rating / LC2 force ≥ safety_factor_yield_LC2 | The rating is the onset "
        "of permanent deformation, which LC2 forbids |",
        f"| LC2 torque | Follows the bought-part change S1 ({number(f7['motor_torque']['value'])} Nm, datasheet) | The YAML's "
        "3 Nm describes the replaced motor; the scenario is unchanged |",
        "| G9 | Box checked in the YAML frame (rigid fit to the IF4 carriages, `src/datum.py`); tool solid excluded | The box "
        "starts at the spindle nose; the tool is below it |",
        f"| G6 | Original travel {config.z_travel['travel_mm']:.2f} mm (old sweep, `evidence/`) carried while the proof holds "
        "| Not recomputed here |",
        "| Prices | Excluding VAT; per piece = amount / VAT divisor / quantity | Comparable prices |",
        f"| Cost model | Removal rate {config.cost_model['removal_rate_mm3_min']} mm³/min; blank = box on the next NP3 plate; "
        f"one setup per hole-axis family; facing {config.cost_model['facing_allowance_mm']} mm | Ours: see "
        "`rules/cost_model.yaml`, `results/manufacturing_review.md` |", "",
        "**Changed bought parts** (YAML `bought_parts`; prices excl. VAT, quoted 2026-11-24):", "",
        "| ID | From → to | Reason | Price from → to (per piece) | Δ €/assy | Source |", "|---|---|---|---|---|---|"]
    g10 = checks["G10_thread_engagement"]["inputs"]
    factor = checks["F7_z_ball_nut_capacity"]["threshold"]["value"]
    original_force = load_case_force(config)
    reasons = {  # short reason per substitution, numbers from the records
        "motor_envelope": lambda s: (f"F7: with the 3 Nm motor the nut factor is {config.z_ball_nut['static_axial_rating_N']['value'] / original_force:.2f} < {number(factor)}; "
                                     f"with {number(f7['motor_torque']['value'])} Nm it is "
                                     f"{checks['F7_z_ball_nut_capacity']['result']['value']:.3f}. Driver current 2.0 A"),
        "socket_head_screw": lambda s: next(
            f"G10: head seat to thread {g10[k + '.head_seat_to_thread']['value']:.1f} mm; the original screws engage 0 mm, "
            f"{s['geometry']['length_mm']:g} mm engage {g10[k + '.engagement']['value']:.1f} mm ≥ 1.5 d"
            for k in (f"{j}_1" for j in ("rear_clamp_m8", "motor_m5"))
            if g10[k + ".nominal_diameter"]["value"] == s["geometry"]["shank_diameter_mm"])}
    for sub in config.substitutions:
        lines.append(f"| {sub['id']} | {sub['from'].split(' (')[0].split(', holding')[0]} → "
                     f"{sub['to'].split(' (')[0].split(', holding')[0]} | {reasons[sub['geometry']['type']](sub)} | "
                     f"{piece_price(sub['price_from']):.4g} → {piece_price(sub['price_to']):.4g} {sub['currency']} | "
                     f"{c3[sub['id'] + '.bought_delta']['value']:+.6f} | "
                     f"{source(sub['price_from'], 'from')}, {source(sub['price_to'], 'to')} |")
    (ROOT / "EVALS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"EVALS.md: {len(lines)} lines")


if __name__ == "__main__":
    main()

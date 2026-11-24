"""Generate the design options of every rule in rules/, grade each one, select the best and write cases/best/.

Options = every value of the design-option rule x every subset of the bought-part substitutions. Writes
results/options/*.step (changed parts in the source frame, verified by reimport), results/options.csv,
results/load_path.json and the winner's STEP files and manifest in --out.
"""

import argparse
import csv
import itertools
import shutil
import sys
import time
from pathlib import Path

import yaml

from src import cache as cache_module
from src.config import ROOT, load_config, override_lines, price_warnings
from src.cost_eval import piece_price
from src.geometry import write_verified_step
from src.function_eval import f7_torque_limit
from src.grade import (Case, assign_solids, blocking_checks, connector_geometry, evaluate_case, option_row, option_solids,
                       substitution_shapes)
from src.load_path import analyze
from src.records import write_json

COLUMNS = ["option_id", "trim_mm", "substitutions", "delta_made_eur", "delta_bought_eur", "delta_total_eur", "f4_bound",
           "f7_safety_factor", "f7_status", "g10_engagement_d", "g10_status", "verdict", "compliance", "remaining_findings",
           "fail_ids", "step_paths"]
SELECTION = "lowest total delta among ACCEPT; tie-break: fewer remaining original findings, then the smaller trim"
SIMPLIFIED = {"motor_envelope": "simplified envelope: body box below the original flange face and the shaft on the original "
                                "axis (no boss, flange holes or wire)",
              "socket_head_screw": "simplified: plain shank and head cylinders on the original head seat and axis (no "
                                   "thread or socket)"}


def parse(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "cases" / "best"), help="folder for the winner (default cases/best)")
    parser.add_argument("--requirements", help="default requirements/subassembly.yaml")
    parser.add_argument("--rates", help="default requirements/rates.yaml")
    parser.add_argument("--cost-model", help="default rules/cost_model.yaml")
    parser.add_argument("--rules", help="folder of rule files (default rules/)")
    parser.add_argument("--results", default=str(ROOT / "results"), help="default results/")
    parser.add_argument("--verbose", action="store_true", help="print all option rows (default: a short summary)")
    parser.add_argument("--set", action="append", default=[], metavar="FILE:KEY=VALUE",
                        help="in-memory override, repeatable, e.g. cost_model:removal_rate_mm3_min=50000 "
                             "(FILE = requirements, rates or cost_model; never written back)")
    return parser.parse_args(argv)


def relative(path):
    path = Path(path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def row_line(row):
    return (f"{row['option_id']:37} {row['verdict']:9} {row['delta_total_eur']:11.6f} {row['f4_bound']:7.4f} "
            f"{row['f7_safety_factor']:6.3f} {row['g10_engagement_d']:6.2f}  {row['fail_ids']}")


def summary_lines(rows, table, verbose=False):
    """All rows (verbose) or the ACCEPT rows plus the number of options failing each check, and where the table is."""
    shown = rows if verbose else [r for r in rows if r["verdict"] == "ACCEPT"]
    counts = {}
    for row in rows:
        for check in row["fail_ids"].split():
            counts[check.split("_")[0]] = counts.get(check.split("_")[0], 0) + 1
    lines = [f"{'option':37} {'verdict':9} {'delta EUR':>11} {'F4':>7} {'F7 SF':>6} {'G10 d':>6}  fails", *map(row_line, shown)]
    if not verbose:
        lines += [f"Options failing each check (of {len(rows)}): "
                  + (", ".join(f"{k}: {v}" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))) or "none")
                  + f". Full table: {table} (or --verbose)."]
    return lines


def select(rows):
    accepted = [r for r in rows if r["verdict"] == "ACCEPT"]
    return min(accepted, key=lambda r: (round(r["delta_total_eur"], 6), r["remaining_findings"], r["trim_mm"])) if accepted else None


def write_best(out, best, config, design_step, sub_steps, rows):
    """Winner STEP files (copies of the verified option files) and the case manifest."""
    out.mkdir(parents=True, exist_ok=True)
    for old in [*out.glob("*.step"), out / "manifest.yaml"]:  # this folder holds only optimizer output
        old.unlink(missing_ok=True)
    rule, chosen = config.rule, [config.substitution(i) for i in best["substitutions"].split("+") if i != "none"]
    shutil.copyfile(design_step, out / "zxverbinder.step")
    for sub in chosen:
        shutil.copyfile(sub_steps[sub["id"]], out / sub_steps[sub["id"]].name)
    attribution = rule["attribution"]
    manifest = {
        "case_id": out.name, "option_id": best["option_id"], "expected_verdict": "ACCEPT",
        "design": {"rule_id": rule["rule_id"], "part_id": rule["part_id"], "step": "zxverbinder.step",
                   "parameter": {"name": rule["parameter"]["name"], "value": best["trim_mm"], "unit": rule["parameter"]["unit"]},
                   "attribution": attribution,
                   "licence": f"Changed design file of {attribution['project']} by {attribution['author']} "
                              f"({attribution['source']}), licensed {attribution['hardware_license']}; it keeps that licence."},
        "substitutions": [{"id": s["id"], "part": s["part"], "from": s["from"], "to": s["to"], "quantity": s["quantity"],
                           "step": sub_steps[s["id"]].name, "geometry": {"model": SIMPLIFIED[s["geometry"]["type"]], **s["geometry"]},
                           "price_from": s["price_from"], "price_to": s["price_to"], "currency": s["currency"],
                           "piece_price_from": piece_price(s["price_from"]), "piece_price_to": piece_price(s["price_to"]),
                           "conversion": s.get("conversion"), "reason": s["reason"]}
                          for s in chosen],
        "selection": {"rule": SELECTION, "options": len(rows), "accepted": sum(r["verdict"] == "ACCEPT" for r in rows),
                      "delta_made_eur": best["delta_made_eur"], "delta_bought_eur": best["delta_bought_eur"],
                      "delta_total_eur": best["delta_total_eur"], "compliance": best["compliance"]}}
    if config.overrides:
        manifest["overrides"] = list(config.overrides)
    (out / "manifest.yaml").write_text("# Written by optimize.py; read by bench.py.\n" + yaml.safe_dump(
        manifest, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")


def main(argv=None):
    args = parse(argv)
    started = time.perf_counter()
    cache = cache_module.load()
    config = load_config(args.requirements, args.rates, args.cost_model, args.rules, args.set)
    for line in override_lines(config):
        print(line)
    overrides = "; ".join(f"{o['file']}:{o['key']}={o['to']!r}" for o in config.overrides)
    results = Path(args.results)
    options_dir = results / "options"
    write_json(results / "load_path.json", analyze(cache, config))

    substitutions, sub_steps = config.substitutions, {}
    measured = {}
    for sub in substitutions:
        declared = substitution_shapes(sub, cache)
        sub_steps[sub["id"]] = options_dir / f"{sub['id']}_{sub['geometry']['type']}.step"
        solids = write_verified_step(sub_steps[sub["id"]], [shape for _, _, shape in declared if shape is not None])
        measured[sub["id"]] = assign_solids(cache, declared, solids)
    subsets = [c for n in range(len(substitutions) + 1) for c in itertools.combinations(substitutions, n)]

    rule, rows, design_steps = config.rule, [], {}
    for value in rule["parameter"]["values"]:
        design_steps[value] = options_dir / f"{rule['rule_id']}_{value:02d}{rule['parameter']['unit']}.step"
        connectors = write_verified_step(design_steps[value], option_solids(cache, rule, value))
        geometry = connector_geometry(cache.connectors, connectors, cache, config)
        for subset in subsets:
            ids = [s["id"] for s in subset]
            option_id = design_steps[value].stem + "".join(f"+{i}" for i in ids)
            replaced = {index: facts for i in ids for index, facts in measured[i].items()}
            report = evaluate_case(Case(option_id, connectors, value, subset, replaced), cache, config, geometry)
            rows.append({"option_id": option_id, "trim_mm": value, "substitutions": "+".join(ids) or "none", **option_row(report),
                         "step_paths": " ".join(relative(p) for p in [design_steps[value], *(sub_steps[i] for i in ids)]),
                         "overrides": overrides})

    results.mkdir(parents=True, exist_ok=True)
    with (results / "options.csv").open("w", newline="", encoding="utf-8") as file:  # overrides column only when used
        writer = csv.DictWriter(file, fieldnames=COLUMNS + ["overrides"] * bool(overrides), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    best = select(rows)
    print(*summary_lines(rows, relative(results / "options.csv"), args.verbose), sep="\n")
    for line in price_warnings(config.substitutions):
        print(line)
    if best is None:
        blocking = blocking_checks([r["fail_ids"] for r in rows])
        print(f"\nNO OPTION IS ACCEPT ({len(rows)} graded). Checks that fail in every option: {', '.join(blocking) or 'none'}.")
        if "F7_z_ball_nut_capacity" in blocking:
            force, torque = f7_torque_limit(config)
            motors = [f"{s['id']} {i['to']} {i['unit']}" for s in config.substitutions for i in s["affected_inputs"]]
            print(f"F7 needs an LC2 force <= {force:.0f} N, i.e. a motor holding torque <= {torque:.3f} Nm "
                  f"(available: {', '.join(motors) or 'none'}).")
        print(f"cases/best is not changed. {SELECTION}.")
        return 1
    write_best(Path(args.out), best, config, design_steps[best["trim_mm"]], sub_steps, rows)
    print(f"\nBest: {best['option_id']}  delta {best['delta_total_eur']:.6f} EUR/assembly (made {best['delta_made_eur']:.6f}, "
          f"bought {best['delta_bought_eur']:.6f}); compliance: {best['compliance']}\n"
          f"{sum(r['verdict'] == 'ACCEPT' for r in rows)} of {len(rows)} options ACCEPT. Wrote {relative(results / 'options.csv')} "
          f"and {relative(args.out)}/ in {time.perf_counter() - started:.1f} s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Grade every case folder in --cases (each has a manifest.yaml): one score row per case, results/<case>.json each.

A manifest names the ZXVerbinder STEP (`design.step`; none = the original solids), the applied substitutions with their
STEP files, `reference: true` for the original, and the expected verdict. Exit code 1 if a verdict differs.
"""

import argparse
import sys
import time
from pathlib import Path

import yaml

from src import cache as cache_module
from src.config import ROOT, load_config, override_lines, price_warnings
from src.geometry import read_step_solids
from src.grade import Case, assign_solids, evaluate_case, option_row, substitution_shapes
from src.records import write_json


def parse(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", default=str(ROOT / "cases"), help="folder of case folders (default cases/)")
    parser.add_argument("--requirements", help="default requirements/subassembly.yaml")
    parser.add_argument("--rates", help="default requirements/rates.yaml")
    parser.add_argument("--cost-model", help="default rules/cost_model.yaml")
    parser.add_argument("--rules", help="folder of rule files (default rules/)")
    parser.add_argument("--results", default=str(ROOT / "results"), help="default results/")
    parser.add_argument("--set", action="append", default=[], metavar="FILE:KEY=VALUE",
                        help="in-memory override, repeatable, e.g. cost_model:removal_rate_mm3_min=50000 "
                             "(FILE = requirements, rates or cost_model; never written back)")
    return parser.parse_args(argv)


def load_case(folder, cache, config):
    """The Case described by folder/manifest.yaml, and its expected verdict."""
    manifest = yaml.safe_load((folder / "manifest.yaml").read_text(encoding="utf-8"))
    design = manifest.get("design")
    connectors = read_step_solids(folder / design["step"]) if design else cache.connectors
    substitutions, replaced = [], {}
    for item in manifest.get("substitutions") or []:
        sub = config.substitution(item["id"])
        substitutions.append(sub)
        replaced.update(assign_solids(cache, substitution_shapes(sub, cache), read_step_solids(folder / item["step"])))
    value = (design or {}).get("parameter", {}).get("value")
    return Case(manifest["case_id"], connectors, value, tuple(substitutions), replaced,
                manifest.get("reference", False)), manifest.get("expected_verdict")


def main(argv=None):
    args = parse(argv)
    started = time.perf_counter()
    cache = cache_module.load()
    config = load_config(args.requirements, args.rates, args.cost_model, args.rules, args.set)
    for line in override_lines(config):
        print(line)
    folders = sorted(p for p in Path(args.cases).iterdir() if (p / "manifest.yaml").is_file())
    header = f"{'case':10} {'Function':8} {'Fit':5} {'Cost':5} {'verdict':9} {'expected':9} {'delta EUR':>11} {'F4':>7} " \
             f"{'F7 SF':>6} {'G10 d':>6}  compliance / failed checks"
    print(header)
    mismatches = 0
    for folder in folders:
        case, expected = load_case(folder, cache, config)
        report = evaluate_case(case, cache, config)
        if config.overrides:  # recorded only when used, so a default run reproduces the default reports exactly
            report["overrides"] = list(config.overrides)
        write_json(Path(args.results) / f"{case.case_id}.json", report)
        row = option_row(report)
        mismatches += expected is not None and expected != row["verdict"]
        print(f"{case.case_id:10} {row['function']:8} {row['fit']:5} {row['cost']:5} {row['verdict']:9} {expected or '-':9} "
              f"{row['delta_total_eur']:11.6f} {row['f4_bound'] if row['f4_bound'] is None else round(row['f4_bound'], 4)!s:>7} "
              f"{row['f7_safety_factor']:6.3f} {row['g10_engagement_d']:6.2f}  {row['compliance']}")
    for line in price_warnings(config.substitutions):
        print(line)
    print(f"{len(folders)} cases in {time.perf_counter() - started:.1f} s; {mismatches} verdict(s) differ from the manifest.")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())

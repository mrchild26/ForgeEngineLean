"""Cost grader C1-C3: material, machine time and setups from the geometry; the change must be less expensive."""

from src.cache import STEP_NAME_ALIASES
from src.geometry import VOLUME_TOL_MM3
from src.records import calculation, measured

UNITS = {"stock_length": "mm", "stock_width": "mm", "stock_thickness": "mm", "solid_volume": "mm^3", "stock_mass": "kg",
         "chip_volume": "mm^3", "milling_time": "min", "setups": "count/lot", "material": "EUR", "milling": "EUR",
         "setup": "EUR", "scrap_credit": "EUR", "total": "EUR"}
FORMULA = ("cost = stock_mass * price + milling_time * (machine_rate + labour_rate)/60 + setups * setup_time * "
           "(machine_rate + labour_rate)/(60 * lot_size) - chip_mass * chip_price; stock_mass = L*W*T*density*1e-6; "
           "T = smallest approved plate >= part thickness + facing_allowance; setups = measured + extra_setups_per_part; "
           "chip_volume = L*W*T - solid_volume; milling_time = chip_volume / removal_rate")


def approved_thickness(finished_thickness, choices):
    return min((t for t in choices if t >= finished_thickness), default=None)


BAR_FORM = "bar price used for a cut-to-size blank"


def material_price(config, material):
    """(rates key, price entry, product-form note): '<alloy> plate', else '<alloy> bar' with a note, else (None, None, None)."""
    materials, key = config.rates["materials"], config.cost_model["material_key"].format(material=material)
    if key in materials:
        return key, materials[key], None
    return (f"{material} bar", materials[f"{material} bar"], BAR_FORM) if f"{material} bar" in materials else (None, None, None)


def plate_cost(spans_sorted_mm, solid_volume_mm3, setups, material, config):
    """Nominal 3-axis milled part from a bounding-box blank on the next approved plate >= thickness + facing allowance.

    cost = stock_mass*price + milling_time*(machine + labour)/60 + setups*setup_time*(machine + labour)/(60*lot)
           - chip_mass*chip_price; milling_time = chip_volume / removal_rate. Returns None without an approved plate.
    """
    rates, model = config.rates, config.cost_model
    supply = {r["id"]: r for r in config.requirements["non_physical_requirements"]["supply"]["rules"]}
    thickness, width, length = spans_sorted_mm
    stock = approved_thickness(thickness + model["facing_allowance_mm"], supply["NP3_stock_thickness"]["plate_thickness_mm"]["value"])
    setups += model["extra_setups_per_part"]
    _, price, form = material_price(config, material)
    if stock is None or price is None:
        return None
    stock_volume = length * width * stock
    # A solid blank equal to the stock within STEP round-off has exactly zero chips.
    volume = min(solid_volume_mm3, stock_volume) if abs(solid_volume_mm3 - stock_volume) <= VOLUME_TOL_MM3 else solid_volume_mm3
    if volume > stock_volume:
        raise ValueError("Finished volume exceeds stock volume")
    machine = rates["machines"][model["machine"]]
    hourly = machine["machine_rate_eur_h"] + rates["labour_rate_eur_h"]
    stock_mass = stock_volume * price["density_g_cm3"] * 1e-6
    chip_volume = stock_volume - volume
    milling_min = chip_volume / model["removal_rate_mm3_min"]
    parts = {"stock_length": length, "stock_width": width, "stock_thickness": stock, "solid_volume": volume,
             "stock_mass": stock_mass, "chip_volume": chip_volume, "milling_time": milling_min, "setups": setups,
             "material": stock_mass * price["price_eur_kg"], "milling": milling_min / 60 * hourly,
             "setup": setups * machine["setup_time_min"] / 60 * hourly / config.lot_size,
             "scrap_credit": chip_volume * price["density_g_cm3"] * 1e-6 * price["chip_value_eur_kg"]}
    parts["total"] = parts["material"] + parts["milling"] + parts["setup"] - parts["scrap_credit"]
    return {**parts, "product_form": form} if form else parts


def part_costs(parts, config):
    """Per made part id: list of per-occurrence estimates (None if any occurrence has no approved plate)."""
    result = {}
    for spec in config.requirements["made_parts"]["parts"]:
        name = STEP_NAME_ALIASES.get(spec["part_id"], spec["part_id"])
        estimates = [plate_cost(p["spans_sorted_mm"], p["volume_mm3"], p["setups"], spec["material"], config)
                     for p in parts if p["name"] == name]
        result[spec["part_id"]] = None if None in estimates else estimates
    return result


def piece_price(price):
    """Per-piece price excluding VAT: amount / (1 + vat_rate if VAT is included) / per_quantity."""
    return price["amount"] / (1 + price["vat_rate"] if price["vat"] == "included" else 1) / price["per_quantity"]


def bought_delta(sub, currency):
    """(EUR/assembly delta, rate) of one substitution: quantity * (piece_price_to - piece_price_from) / rate."""
    difference = sub["quantity"] * (piece_price(sub["price_to"]) - piece_price(sub["price_from"]))
    if sub["currency"] == currency:
        return difference, 1.0
    conversion = sub["conversion"]
    if conversion["unit"] != f"{sub['currency']}/{currency}":
        raise ValueError(f"{sub['id']}: conversion unit {conversion['unit']} does not convert {sub['currency']} to {currency}")
    return difference / conversion["rate"], conversion["rate"]


def cost_checks(original_parts, case_parts, changed_part, config, substitutions=()):
    rates, model = config.rates, config.cost_model
    before, after = part_costs(original_parts, config), part_costs(case_parts, config)
    total = {k: {p: sum(e["total"] for e in v[p]) if v[p] is not None else None for p in v} for k, v in (("original", before), ("case", after))}
    material = next(s["material"] for s in config.requirements["made_parts"]["parts"] if s["part_id"] == changed_part)
    key, price, form = material_price(config, material)
    if price is None:
        raise ValueError(f"No price for {material}: add 'materials.{material} plate' (or '... bar') to rates.yaml")
    machine = rates["machines"][model["machine"]]
    inputs = {"machine_rate": measured(machine["machine_rate_eur_h"], "EUR/h"), "labour_rate": measured(rates["labour_rate_eur_h"], "EUR/h"),
              "setup_time": measured(machine["setup_time_min"], "min/setup"), "lot_size": measured(config.lot_size, "parts/lot"),
              "removal_rate": measured(model["removal_rate_mm3_min"], "mm^3/min"), "density": measured(price["density_g_cm3"], "g/cm^3"),
              "facing_allowance": measured(model["facing_allowance_mm"], "mm"),
              "extra_setups_per_part": measured(model["extra_setups_per_part"], "count/part"),
              "price": measured(price["price_eur_kg"], "EUR/kg"), "chip_price": measured(price["chip_value_eur_kg"], "EUR/kg")}
    for i, estimate in enumerate(after[changed_part] or [], 1):
        inputs.update({f"occurrence_{i}.{k}": measured(v, UNITS[k]) for k, v in estimate.items() if k in UNITS})
    checks = {"C1_changed_part_cost": calculation(
        f"sum over {changed_part} occurrences of [{FORMULA}]", inputs, total["case"][changed_part], total["original"][changed_part],
        "EUR/assembly", reason="Changed part only; the original part cost is the comparator. Recompute one occurrence by hand."
        + (f" Product form: {form} (rates.yaml '{key}')." if form else ""))}
    known = {k: None if None in v.values() else sum(v.values()) for k, v in total.items()}
    checks["C2_manufacturing_cost"] = calculation(
        "sum over all made part types and occurrences of the per-part cost", {
            **{f"case.{p}": measured(v, "EUR/assembly") for p, v in total["case"].items() if v is not None},
            **({"original_total": measured(known["original"], "EUR/assembly")} if known["original"] is not None else {})},
        known["case"], known["original"], "EUR/assembly", reason="All ten made parts at their quantities.")
    currency = rates["currency"]
    inputs, bought = {}, 0.0
    for sub in substitutions:
        term, rate = bought_delta(sub, currency)
        bought += term
        inputs[f"{sub['id']}.quantity"] = measured(sub["quantity"], "pieces/assembly")
        for side in ("price_from", "price_to"):
            price, unit = sub[side], sub["currency"]
            inputs.update({f"{sub['id']}.{side}.amount": measured(price["amount"], f"{unit}/{price['per_quantity']} pieces"),
                           f"{sub['id']}.{side}.per_quantity": measured(price["per_quantity"], "pieces"),
                           f"{sub['id']}.{side}.pack_size": measured(price["pack_size"], "pieces"),
                           f"{sub['id']}.{side}.vat_divisor": measured(1 + price["vat_rate"] if price["vat"] == "included" else 1, "1"),
                           f"{sub['id']}.{side}.piece_price": measured(piece_price(price), f"{unit}/piece")})
        inputs.update({f"{sub['id']}.rate": measured(rate, f"{sub['currency']}/{currency}"),
                       f"{sub['id']}.bought_delta": measured(term, f"{currency}/assembly")})
    made_delta = known["case"] - known["original"] if None not in known.values() else None
    if made_delta is not None:
        inputs = {"case_manufacturing_cost": measured(known["case"], "EUR/assembly"),
                  "original_manufacturing_cost": measured(known["original"], "EUR/assembly"),
                  "made_parts_delta": measured(made_delta, "EUR/assembly"), **inputs}
    inputs["bought_parts_delta"] = measured(bought, "EUR/assembly")
    checks["C3_cost_delta"] = calculation(
        "delta = (case_manufacturing_cost - original_manufacturing_cost) + sum over substitutions of "
        "quantity * (piece_price_to - piece_price_from) / rate; piece_price = amount / vat_divisor / per_quantity",
        inputs, None if made_delta is None else made_delta + bought, 0,
        "EUR/assembly", operator="<", reason="Less expensive: delta < 0. Unchanged bought parts add 0 (rates.yaml); a "
        "changed bought part adds its price difference excluding VAT, converted to EUR with the recorded rate.")
    return checks

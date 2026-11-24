# Rule file format

A rule is one YAML file in `rules/` with a `rule_type` key. `rules/schema.yaml` is the machine-readable form of this page
(one schema per `rule_type`); `src/config.py:load_rules` validates every rule file in the folder against it before use.
Files without `rule_type` (`schema.yaml`, `cost_model.yaml`) are not rules. Any system can apply a rule with the
semantics below. Coordinates are those of the source STEP assembly, in mm.

The optimizer combines every value of the design-option rule with every subset of the bought-part substitutions.

## `rule_type: design_option`

Generates design options for one made part.

| Field | Type | Meaning |
|---|---|---|
| `rule_type` | enum | `design_option`. |
| `rule_id` | string | Name of the rule. Option ids are `<rule_id>_<value:02d><unit>`, e.g. `zxverbinder_trim_02mm`, plus `+<substitution id>` per applied substitution. |
| `schema_version` | integer | Version of this format (1). |
| `part_id` | string | Name of the made part in the STEP file and in `subassembly.yaml made_parts`. Every occurrence of the part gets the same change. |
| `operation` | enum | `symmetric_end_trim`: remove a slab of the same thickness from both ends of the part along `axis`. The part's own bounding box gives the ends; the slab spans the full section. |
| `axis` | enum | `X`, `Y` or `Z` of the source STEP frame. Each occurrence's placement must keep this axis (mirrors allowed). |
| `parameter.name` | enum | `trim_depth`: the thickness removed from each end. |
| `parameter.unit` | enum | `mm`. |
| `parameter.values` | list of integers ≥ 1, unique | One design option per value. |
| `protected_features.bolt_seat_radius_mm` | number > 0 | Radius around each mounting-hole axis that must stay unchanged (the bolt seat). |
| `protected_features.features` | list of enum | Features the operation must preserve exactly: `mounting_holes` (all cylindrical bores), `bolt_seats` (material within the seat radius of each bore axis), `ball_nut_face` (the planar face at the part's minimum Y, used by the X ball-nut carrier). An option whose cut reaches the protected region is invalid. |
| `original_step` | string | Source STEP assembly, relative to the repository root. |
| `attribution` | map | `project`, `author`, `source`, `hardware_license` of the source CAD. Changed design files keep this licence. |
| `unchanged_proofs` | map: check id → text | Why this change cannot affect each requirement graded UNCHANGED (F5, F6, F7, G6, G9, G10, G12). A check without a reason cannot be UNCHANGED for a case with this change: it is computed, or FAIL. |

**Validity of an option.** The operation must leave one valid solid per occurrence. The changed solid must lie inside
the original (removal only). The protected region must keep its volume to 0.01 mm³. The graders check all three; see EVALS.md.

## `rule_type: bought_part_substitution`

Replaces bought parts (`subassembly.yaml bought_parts`: "give the reason, the price and the source of the price").

| Field | Type | Meaning |
|---|---|---|
| `rule_type` | enum | `bought_part_substitution`. |
| `rule_id`, `schema_version` | string, integer | As above. |
| `substitutions` | list | One entry per substitution, applied independently. |
| `…id` | string | Unique substitution id, e.g. `S1`. |
| `…part` | string | STEP part name of the replaced part; every occurrence is replaced. |
| `…includes` | list of strings, optional | Other STEP parts that belong to the replaced part and are removed with it (e.g. the motor wire). |
| `…quantity` | integer ≥ 1 | Pieces per assembly; must equal the number of STEP occurrences of `part` (checked by G0). |
| `…from`, `…to` | string | Designation and key data of the old and the new part, with their source. |
| `…reason` | string | Why the part changes (requirement and numbers). |
| `…affected_inputs` | list | Requirement inputs that describe the replaced part: `path` (dotted path in `subassembly.yaml`; a list step selects the item whose `id` starts with the key), `from` (must equal the YAML value), `to`, `unit`, `source`. The graders re-evaluate the requirement with `to`; the YAML file is not edited. Implemented: `load_cases.LC2_crash.derivation.motor_torque_Nm`. |
| `…price_from`, `…price_to` | map | Price of the old and the new part as shown by the source: `amount` (in `currency`) for `per_quantity` pieces, `pack_size` (pieces per sales unit), `vat` (`excluded` or `included`; `included` needs `vat_rate`, e.g. 0.19), `article`, `url`, `accessed` (date), `status` (`quoted`: read from the source; `unconfirmed`: placeholder), `note`. Prices are compared excluding VAT: piece price = amount / (1 + vat_rate if included) / per_quantity, recorded in C3. |
| `…currency` | string | Price currency. Not EUR → `conversion` is required. |
| `…conversion` | map, optional | `rate` and `unit` (e.g. 1.1127 `USD/EUR`: EUR = USD / rate), `date`, `source`, `url`, `accessed`. |
| `…geometry` | map | Simplified solid written to the STEP output, placed on the replaced part's `anchor`. `motor_envelope`: `body_mm` [width, depth, length] below the original flange face, `shaft_diameter_mm`, `shaft_length_mm` above it, on the original shaft axis. `socket_head_screw`: `shank_diameter_mm`, `length_mm`, `head_diameter_mm`, `head_height_mm`, on the original head seat and axis. |
| `…drive_check` | map, optional | Inputs of the informational Z drive check: `acceleration_m_s2`, `bought_part_density_g_cm3`, `source` (the plunge force is the LC1 force of subassembly.yaml); optional `speed_safety_factor` and `pull_out_torque` (`source`, `conditions`, `points_rpm_Ncm` [[rpm, N·cm], …]) for the highest Z speed with pull-out torque ≥ factor × required torque. |
| `…unchanged_proofs` | map: check id → text | As above: why this substitution cannot affect each requirement graded UNCHANGED. |

**Validity of a substitution.** G0 checks that each replaced part equals its declared simplified solid at the anchor,
that the quantity matches and (motor) that the new shaft stays clear of the ball-screw journal. G17 requires the reason
and both prices, each with a source URL. C3 adds `quantity * (piece_price_to - piece_price_from) / rate` per substitution.
Screw geometry is anchored on the cached threaded joints (rear-clamp M8, motor M5): original head seat and axis.

# Coordinate transformation approaches

This repository contains two different kinds of coordinate work:

1. **Coordinate representation and cleanup** - preserving a supplied location while making its text suitable for Darwin Core; and
2. **Sensitive-species generalisation** - deliberately publishing a less precise derivative of a location (or withholding it) to reduce disclosure risk.

They solve different problems. A DMS cleanup must never be presented as a sensitive-data safeguard, and a sensitive-data transformation should be run only on the public export, while the authoritative source coordinate remains protected.

## 1. Representation and cleanup (`transformation/coordinates.py`)

| Function | Logic | Result | Limitations / use |
| --- | --- | --- | --- |
| `construct_coordinate_string` | Joins present degrees, minutes, seconds, and direction values using DMS symbols. | One DMS string, for example `59° 20' 0'' N`. | It formats values; it does not validate ranges, infer a hemisphere, or produce decimal degrees. |
| `generate_dms_coordinates_column` | Requires four component columns, applies `construct_coordinate_string` per row, and writes a named column. | A verbatim latitude or longitude field. | Appropriate when source fields are separate DMS components (as in the pollen and FBO configurations). It raises `KeyError` if a component column is absent. |
| `clean_coordinates` | Splits a coordinate string on whitespace and normalises compact DMS tokens matching `degrees°minutes'seconds''direction`. It removes empty minute/second components. | Standardised text such as `59°20'N`, without changing its stated position. | The regular expression accepts unsigned integer components only and does not validate latitude/longitude bounds. Non-matching text is retained unchanged. |
| `update_coordinates` | Converts nulls to empty strings, calls `clean_coordinates`, and writes the result to `verbatimCoordinates`. | A cleaned Darwin Core verbatim-coordinate value; source column remains available. | It is a textual operation, not a CRS transformation or a privacy control. |

`apply_transformations` in `transformation/transform.py` dispatches `generate_dms_coordinates_column` and `update_coordinates` from YAML configuration. The module also re-exports these helpers for callers using Python directly.

## 2. Sensitive-coordinate transformations (`transformation/sensitive_species.py`)

All three public-data approaches operate on WGS84 decimal latitude/longitude, but their rule models, grids, and outputs are materially different.

| Approach and ETL function | Rule selection | Spatial logic | Public coordinate / uncertainty | Metadata and withholding behaviour |
| --- | --- | --- | --- | --- |
| **SOS diffusion** `sds_diffusion_sos` | Uses an existing `sensitivityCategory` (2-5), or looks up a Swedish restricted-species CSV by `taxonID` first and scientific name second. The explicit mapping is `1km -> 2`, `5km -> 3`, `25km -> 4`, `50km -> 5`. | Projects WGS84 to SWEREF99 TM (EPSG:3006); snaps each axis to the lower grid edge and adds the SOS offset; reprojects to WGS84. Levels use grids/offsets of 1,000/555 m, 5,000/2,505 m, 25,000/12,505 m, and 50,000/25,005 m. | One deterministic point inside each SOS grid cell. `coordinateUncertaintyInMeters` becomes at least the grid size. | Adds the location-removal statement to `dataGeneralizations` and sets `diffusionStatus=DiffusedBySystem`. Unmatched taxa and invalid/no-level rows are unchanged. It does not suppress a matched coordinate. |
| **ALA / SDS generalisation** `sds_generalization_ala` | Loads ALA/GBIF SDS XML (`guid`/name, optional `dataResourceId`, optional precomputed zone) or the Swedish CSV. If several rules match, the largest distance, including `WITHHOLD`, wins. | Applies the SDS latitude/longitude algorithm: round on an approximate metre grid using 111,132.9 m per degree; scale longitude by cosine of the original latitude; then format at 0.01 degrees for <=1 km, 0.1 degrees for <=10 km, otherwise whole degrees. | Display-ready coordinate strings. In the tested 5 km example, `-37.2234, 145.786` becomes `-37.2, 145.8`. | Appends `Coordinates generalized using SDS rule ...` to `dataGeneralizations`. `WITHHOLD` sets both coordinates to null and records `Precise original coordinates withheld.` `coordinateUncertaintyInMeters` is not set or recalculated. |
| **GBIF-guide policy** `sds_generalization_gbif` | Requires a governed policy record per scientific name: `category`, `reason`, ISO review date, and original coordinate precision. Categories are `low`, `medium`, `high`, `extreme`, and `not_sensitive`. | Decimal geographic-grid rounding with `ROUND_HALF_UP`: low = 0.001 degrees, medium = 0.01, high = 0.1. Extreme does not release coordinates. | Generalised point plus `coordinatePrecision`; whole-cell geodesic uncertainty is calculated from the rounded point to the farthest cell corner and added to source uncertainty. | Carries sensitivity category, reason, review date, and original precision. `extreme`, expired policy, and invalid records suppress coordinates. An unmatched taxon is explicitly public; `not_sensitive` is explicitly unrestricted. |

### Related SOS diagnostic code

`create_diffused_coordinate_info` is not the production ETL transformation. Its `web_mercator` option compares a Web Mercator SOS-offset calculation, while its `sweref99_tm` option uses the exact cell centre. The latter intentionally produces a different point (`modulo 5,000 = 2,500`) than production `diffuse_coordinates` (`2,505`). The test suite codifies this distinction. Use `sds_diffusion_sos` for an export, not this diagnostic helper.

## Evidence from tests and reference implementations

- `test_sos_diffusion_matches_production_and_diagnostic_modes` confirms that the production SOS offset is deliberate and must not be replaced by a grid-centre calculation.
- `test_sds_diffusion_sos_derives_levels_from_restricted_species_csv` confirms CSV-driven SOS matching, status assignment, and that unmatched records retain their original longitude.
- `test_sds_generalization_ala_applies_zone_and_withhold_rules` confirms XML matching by taxon/resource/zone, the 5 km SDS output, `WITHHOLD`, and YAML dispatcher integration.
- `references/new/sensitive_species_generalization_sos.py` is the matching SOS reference implementation. `references/la/sensitive_data_generalise.py` is the standalone ALA/SDS XML generaliser. `references/new/sensitive_species_generalization.py` is the guide-first model that informed the GBIF-policy path.
- The bundled GBIF best-practice guide recommends documented generalisation rather than random offsets. Its Table 7 uses decimal geographic grids: high = 0.1 degrees, medium = 0.01, low = 0.001, extreme = no coordinate release. It also calls for `coordinateUncertaintyInMeters`, the public and held precision, sensitivity rationale, review date, and use of Darwin Core `dataGeneralizations`/`informationWithheld` when dedicated terms are unavailable.

## Comparison and trade-offs

### Geographic meaning

SOS diffusion preserves Swedish operational compatibility: it uses the national SWEREF99 TM metric grid and the same deterministic, non-centre offset as SOS. This is the best choice when a public export must reproduce SOS-style locations.

ALA/SDS applies a rule-distance model but publishes rounded decimal degrees after an approximate metric calculation. It is useful when the governing source is SDS XML or a compatible list, particularly where rule scope depends on resource and precomputed zone. Its output is easy to display, but the grid is not a single fixed national metric grid and the current ETL does not communicate a quantitative uncertainty.

The GBIF-policy transformation follows the bundled guide most closely for public Darwin Core publication. Its categories are publication policy, not kilometres. It makes the policy decision auditable, provides explicit review handling, and calculates a whole-cell uncertainty. A Swedish 5 km rule cannot be mechanically treated as a GBIF category: the supplied policy CSV currently makes that decision explicitly (for example, mapping 5 km to `high`; 25/50 km to `extreme`) and marks it for review.

### Safety behaviour

SOS is permissive for unmatched records: it leaves them untouched. That is suitable only when the restricted-species list is known to be complete and has an agreed release policy.

ALA/SDS is conservative only for rules that match. `WITHHOLD` is the strong control, but zone matching depends on the caller supplying an already-determined zone; the XML names a zone and does not contain its geometry.

GBIF-policy is strongest for policy governance: expired rules and invalid sensitive-transformation inputs are suppressed rather than released. However, its current restriction-list design still releases unmatched taxa. If publication policy requires an allow-list or review before any release, this must be enforced upstream or by changing the unmatched-taxon's behaviour.

## Recommendation

**For the current Swedish birds pipeline, retain `sds_diffusion_sos` as the production transformation.** It is already configured in `config-files/birds.yml`, consumes the Swedish restricted-access list, uses the reference SOS SWEREF99 TM diffusion algorithm, and is covered by focused tests. Keep the explicit kilometre-to-protection-level mapping in configuration and validate it whenever the source list changes.

**For a public GBIF-facing release policy, adopt `sds_generalization_gbif` as the strategic target once a curator approves and maintains the policy CSV.** It best implements the documentation and governance recommended by the bundled guide: rule rationale, review dates, original/public precision, whole-cell uncertainty, and coordinate suppression for extreme or review-due records. Do not infer GBIF categories from a distance-only list at run time; continue to keep that mapping as an explicit, reviewed policy decision.

Use `sds_generalization_ala` only where the authoritative rules are the SDS XML/CSV and its resource/zone semantics are required. Before publishing with it, add a verified `coordinateUncertaintyInMeters` policy and ensure zone assignment is calculated outside this function. Do not chain SOS, ALA/SDS, and GBIF generalisation on the same public coordinate: choose one approved public derivative per outlet, otherwise cumulative transformations obscure the actual precision and protection level.

## Operational checklist

- Preserve exact coordinates in restricted source storage; create a separate public DataFrame/export.
- Run DMS-formatting helpers only for verbatim values; they are not sensitive-data controls.
- Use taxon IDs where available, retain scientific-name fallback only as a documented fallback, and test representative rules including `WITHHOLD` and unmatched records.
- Populate and publish `coordinateUncertaintyInMeters`, `dataGeneralizations`, and `informationWithheld` consistently. For the GBIF path also retain reason, review date, public precision, and held precision.
- Review the restricted list and GBIF policy before release and on the policy's recorded review dates.
- Test the configured transformation with a small, approved fixture before each ruleset or projection-library change.

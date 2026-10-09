"""Sensitive species coordinate generalization module for Darwin Core ETL.

Implements SDS (Sensitive Data Service) generalization logic based on SWEREF99 TM
(EPSG:3006) grid cells and returns WGS84 (EPSG:4326) cell center coordinates with
whole-cell uncertainty.
"""

from __future__ import annotations

import csv
import logging
import math
import random
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

try:
    import pyproj

    _HAS_PYPROJ = True
    _TO_SWEREF99 = pyproj.Transformer.from_crs(
        "EPSG:4326", "EPSG:3006", always_xy=True
    )
    _TO_WGS84 = pyproj.Transformer.from_crs("EPSG:3006", "EPSG:4326", always_xy=True)
    _GEOD = pyproj.Geod(ellps="GRS80")
except ImportError:
    _HAS_PYPROJ = False

# SOS uses a point within each grid square. The values intentionally match
# CoordinateDiffusionManager in SOS.Harvest.
_DIFFUSION_VALUES: dict[int, tuple[int, int]] = {
    2: (1_000, 555),
    3: (5_000, 2_505),
    4: (25_000, 12_505),
    5: (50_000, 25_005),
}
_SDS_GENERALISATION_RE = re.compile(r"\s*(\d+)\s*(m|km)\s*", re.IGNORECASE)
_SDS_DEGREE_TO_METRES = 111132.9
_GBIF_GUIDE_PRECISIONS: dict[str, float] = {
    "high": 0.1,
    "medium": 0.01,
    "low": 0.001,
}
_GBIF_NOT_SENSITIVE_CATEGORY = "not_sensitive"
_GBIF_GUIDE_CATEGORIES = frozenset(
    {"extreme", _GBIF_NOT_SENSITIVE_CATEGORY, *_GBIF_GUIDE_PRECISIONS}
)
_DEFAULT_SOS_LEVEL_BY_GENERALISATION = {
    "1km": 2,
    "5km": 3,
    "25km": 4,
    "50km": 5,
}


@dataclass(frozen=True)
class SdsXmlConservationInstance:
    """A conservation-instance rule from ALA/GBIF SDS XML."""

    generalisation: str
    zone: str | None
    data_resource_id: str | None
    authority: str | None
    category: str | None


def _name_key(value: str) -> str:
    """Normalize presentation differences, without guessing taxonomic synonyms."""
    return " ".join(unicodedata.normalize("NFC", value).split()).casefold()


def load_gbif_generalization_rules(
    rules_source: str | Path | list[Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    """Load governed GBIF guide policy rules indexed by scientific name.

    Each rule must provide ``scientificName``, ``category``, ``reason``,
    ``reviewDate`` (ISO-8601), and ``originalCoordinatePrecision``. These
    policy values are deliberately not inferred from kilometre-grid rules.
    """
    if isinstance(rules_source, (str, Path)):
        with Path(rules_source).open(encoding="utf-8-sig", newline="") as stream:
            records = list(csv.DictReader(stream))
    else:
        records = rules_source

    rules: dict[str, dict[str, str]] = {}
    required = {
        "scientificName",
        "category",
        "reason",
        "reviewDate",
        "originalCoordinatePrecision",
    }
    for record in records:
        missing = [field for field in required if not str(record.get(field, "")).strip()]
        if missing:
            raise ValueError(
                "GBIF sensitivity rule is missing required fields: "
                + ", ".join(sorted(missing))
            )
        category = str(record["category"]).strip().casefold()
        if category not in _GBIF_GUIDE_CATEGORIES:
            raise ValueError(f"Unsupported GBIF guide category: {record['category']!r}")
        try:
            review_date = date.fromisoformat(str(record["reviewDate"]).strip())
        except ValueError as exc:
            raise ValueError("reviewDate must use ISO-8601 YYYY-MM-DD format") from exc
        name = str(record["scientificName"]).strip()
        key = _name_key(name)
        if key in rules:
            raise ValueError(f"Duplicate GBIF sensitivity rule for {name!r}")
        rules[key] = {
            "scientificName": name,
            "category": category,
            "reason": str(record["reason"]).strip(),
            "reviewDate": review_date.isoformat(),
            "originalCoordinatePrecision": str(
                record["originalCoordinatePrecision"]
            ).strip(),
        }
    return rules


def _gbif_round(value: float, precision: float) -> float:
    """Round decimal degrees deterministically, including half values."""
    from decimal import Decimal, ROUND_HALF_UP

    return float(
        Decimal(str(value)).quantize(Decimal(str(precision)), rounding=ROUND_HALF_UP)
    )


def _gbif_whole_cell_uncertainty(
    lat: float, lon: float, precision: float, original_uncertainty_m: float
) -> int:
    """Calculate a point radius enclosing a decimal geographic grid cell."""
    half = precision / 2
    distances = [
        _geodesic_distance(lon, lat, corner_lon, corner_lat)
        for corner_lat in (lat - half, lat + half)
        for corner_lon in (lon - half, lon + half)
    ]
    return math.ceil(max(distances) + original_uncertainty_m)


def gbif_generalize_observation(
    scientific_name: str,
    latitude: float,
    longitude: float,
    *,
    rules: Mapping[str, Mapping[str, str]],
    original_uncertainty_m: float,
    today: date | None = None,
) -> dict[str, Any]:
    """Apply the GBIF guide's governed decimal-geographic-grid policy."""
    lat, lon, uncertainty = float(latitude), float(longitude), float(original_uncertainty_m)
    if not scientific_name or not scientific_name.strip():
        raise ValueError("scientific_name must be non-empty")
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Coordinates must be finite WGS84 latitude/longitude")
    if not math.isfinite(uncertainty) or uncertainty < 0:
        raise ValueError("original_uncertainty_m must be finite and >= 0")

    rule = rules.get(_name_key(scientific_name))
    if rule is None:
        return {
            "status": "not_listed_public",
            "sensitive": False,
        }
    required = {
        "scientificName",
        "category",
        "reason",
        "reviewDate",
        "originalCoordinatePrecision",
    }
    missing = [field for field in required if not str(rule.get(field, "")).strip()]
    if missing:
        raise ValueError(
            "GBIF sensitivity rule is missing required fields: "
            + ", ".join(sorted(missing))
        )
    category = str(rule["category"]).casefold()
    if category not in _GBIF_GUIDE_CATEGORIES:
        raise ValueError(f"Unsupported GBIF guide category: {rule['category']!r}")
    try:
        review_date = date.fromisoformat(str(rule["reviewDate"]))
    except ValueError as exc:
        raise ValueError("reviewDate must use ISO-8601 YYYY-MM-DD format") from exc
    metadata = {
        "matchedScientificName": rule["scientificName"],
        "sensitive": category != _GBIF_NOT_SENSITIVE_CATEGORY,
        "sensitivityCategory": category,
        "sensitivityReason": rule["reason"],
        "sensitivityReviewDate": review_date.isoformat(),
        "originalCoordinatePrecision": rule["originalCoordinatePrecision"],
    }
    if review_date < (today or date.today()):
        return {
            "status": "sensitivity_review_due",
            **metadata,
            "informationWithheld": "Coordinates withheld because the sensitivity rule requires review.",
        }
    if category == _GBIF_NOT_SENSITIVE_CATEGORY:
        return {
            "status": "not_sensitive",
            **metadata,
        }
    if category == "extreme":
        return {
            "status": "coordinates_suppressed",
            **metadata,
            "dataGeneralizations": "Geographic coordinates withheld because this is an extremely sensitive taxon.",
            "informationWithheld": "Precise locality and coordinates withheld to protect a sensitive species; detailed data may be supplied on request.",
        }

    precision = _GBIF_GUIDE_PRECISIONS[category]
    generalized_lat = _gbif_round(lat, precision)
    generalized_lon = _gbif_round(lon, precision)
    return {
        "status": "generalized",
        **metadata,
        "decimalLatitude": generalized_lat,
        "decimalLongitude": generalized_lon,
        "coordinatePrecision": precision,
        "coordinateUncertaintyInMeters": _gbif_whole_cell_uncertainty(
            generalized_lat, generalized_lon, precision, uncertainty
        ),
        "dataGeneralizations": (
            "Coordinates generalized using a decimal geographic grid and rounded to "
            f"{precision:g} degree; protected source precision: "
            f"{rule['originalCoordinatePrecision']}."
        ),
        "informationWithheld": "Precise original coordinates withheld to protect a sensitive species; detailed data may be supplied on request.",
    }


def _wgs84_to_sweref99tm_fallback(lat: float, lon: float) -> tuple[float, float]:
    """Pure-Python GRS80 / SWEREF99 TM Transverse Mercator Forward Projection."""
    a = 6378137.0
    f = 1 / 298.257222101
    k0 = 0.9996
    lambda0 = math.radians(15.0)
    FE = 500000.0
    FN = 0.0

    phi = math.radians(lat)
    lam = math.radians(lon)

    e2 = f * (2 - f)
    n = f / (2 - f)
    a_deg = (a / (1 + n)) * (1 + (n**2) / 4 + (n**4) / 64)

    alpha = [
        0,
        1 / 2 * n - 2 / 3 * n**2 + 5 / 16 * n**3 + 41 / 180 * n**4,
        13 / 48 * n**2 - 3 / 5 * n**3 + 557 / 1440 * n**4,
        61 / 240 * n**3 - 103 / 140 * n**4,
        49561 / 161280 * n**4,
    ]

    d_lam = lam - lambda0
    tau = math.tan(phi)
    sigma = math.sinh(e2**0.5 * math.atanh(e2**0.5 * tau / math.sqrt(1 + tau**2)))
    tau_p = tau * math.sqrt(1 + sigma**2) - sigma * math.sqrt(1 + tau**2)

    xi_p = math.atan2(tau_p, math.cos(d_lam))
    eta_p = math.atanh(math.sin(d_lam) / math.sqrt(1 + tau_p**2))

    xi = xi_p
    eta = eta_p

    for j in range(1, 5):
        xi += alpha[j] * math.sin(2 * j * xi_p) * math.cosh(2 * j * eta_p)
        eta += alpha[j] * math.cos(2 * j * xi_p) * math.sinh(2 * j * eta_p)

    northing = k0 * a_deg * xi + FN
    easting = k0 * a_deg * eta + FE

    return easting, northing


def _sweref99tm_to_wgs84_fallback(
    easting: float, northing: float
) -> tuple[float, float]:
    """Pure-Python GRS80 / SWEREF99 TM Transverse Mercator Inverse Projection."""
    a = 6378137.0
    f = 1 / 298.257222101
    k0 = 0.9996
    lambda0 = math.radians(15.0)
    FE = 500000.0
    FN = 0.0

    e2 = f * (2 - f)
    e = math.sqrt(e2)
    n = f / (2 - f)
    a_deg = (a / (1 + n)) * (1 + (n**2) / 4 + (n**4) / 64)

    beta = [
        0,
        1 / 2 * n - 2 / 3 * n**2 + 37 / 96 * n**3 - 1 / 360 * n**4,
        1 / 48 * n**2 + 1 / 15 * n**3 - 437 / 1440 * n**4,
        17 / 480 * n**3 - 37 / 840 * n**4,
        4397 / 161280 * n**4,
    ]

    xi = (northing - FN) / (k0 * a_deg)
    eta = (easting - FE) / (k0 * a_deg)

    xi_p = xi
    eta_p = eta

    for j in range(1, 5):
        xi_p -= beta[j] * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
        eta_p -= beta[j] * math.cos(2 * j * xi) * math.sinh(2 * j * eta)

    tau_p = math.sin(xi_p) / math.sqrt(math.sinh(eta_p) ** 2 + math.cos(xi_p) ** 2)

    tau = tau_p
    for _ in range(10):
        sigma = math.sinh(e * math.atanh(e * tau / math.sqrt(1 + tau**2)))
        tau_p_calc = tau * math.sqrt(1 + sigma**2) - sigma * math.sqrt(1 + tau**2)
        diff = tau_p_calc - tau_p
        if abs(diff) < 1e-12:
            break
        g = math.sqrt(1 + tau**2)
        h = math.sqrt(1 + sigma**2)
        tau -= diff / (h / g * math.sqrt(1 + (1 - e**2) * tau**2))

    phi = math.atan(tau)
    d_lam = math.atan2(math.sinh(eta_p), math.cos(xi_p))
    lam = lambda0 + d_lam

    return math.degrees(phi), math.degrees(lam)


def _project_wgs84_to_sweref99(lon: float, lat: float) -> tuple[float, float]:
    if _HAS_PYPROJ:
        x, y = _TO_SWEREF99.transform(lon, lat)
        return float(x), float(y)
    return _wgs84_to_sweref99tm_fallback(lat, lon)


def _project_sweref99_to_wgs84(x: float, y: float) -> tuple[float, float]:
    if _HAS_PYPROJ:
        lon, lat = _TO_WGS84.transform(x, y)
        return float(lon), float(lat)
    lat, lon = _sweref99tm_to_wgs84_fallback(x, y)
    return lon, lat


def _geodesic_distance(
    lon1: float, lat1: float, lon2: float, lat2: float
) -> float:
    if _HAS_PYPROJ:
        _, _, distance = _GEOD.inv(lon1, lat1, lon2, lat2)
        return float(distance)

    # Haversine distance formula fallback (meters)
    r = 6371008.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _java_round(value: float) -> int:
    """Match Java Math.round, including negative ties."""
    return math.floor(value + 0.5)


def sds_generalisation_metres(rule: str) -> int:
    """Parse an ALA/GBIF SDS ``5km``/``100m``/``WITHHOLD`` rule."""
    if rule.upper() == "WITHHOLD":
        return 1_000_000
    match = _SDS_GENERALISATION_RE.fullmatch(rule)
    if not match:
        raise ValueError(f"Invalid SDS generalisation: {rule!r}")
    value = int(match.group(1))
    return value * 1_000 if match.group(2).casefold() == "km" else value


def sds_generalise_coordinates(
    latitude: float, longitude: float, rule: str
) -> tuple[str | None, str | None]:
    """Apply the latitude/longitude SDS GeneralisationRule algorithm."""
    if rule.upper() == "WITHHOLD":
        return None, None

    metres = sds_generalisation_metres(rule)
    if metres <= 1_000:
        precision, decimal_places = 0.01, 2
    elif metres <= 10_000:
        precision, decimal_places = 0.1, 1
    else:
        precision, decimal_places = 1.0, 0

    original_latitude = latitude
    latitude = (
        _java_round(latitude * _SDS_DEGREE_TO_METRES / metres)
        * metres
        / _SDS_DEGREE_TO_METRES
    )
    latitude = _java_round(latitude / precision) * precision
    if -89.9 <= original_latitude <= 89.9:
        conversion = _SDS_DEGREE_TO_METRES * math.cos(math.radians(original_latitude))
        longitude = _java_round(longitude * conversion / metres) * metres / conversion
    longitude = _java_round(longitude / precision) * precision
    return f"{latitude:.{decimal_places}f}", f"{longitude:.{decimal_places}f}"


def load_sds_xml_rules(
    xml_path: str | Path,
) -> dict[str, dict[str, list[SdsXmlConservationInstance]]]:
    """Load ALA/GBIF SDS ``sensitive-species-data.xml`` rules once."""
    by_taxon_id: dict[str, list[SdsXmlConservationInstance]] = {}
    by_name: dict[str, list[SdsXmlConservationInstance]] = {}
    root = ET.parse(xml_path).getroot()
    for species in root.findall(".//sensitiveSpecies"):
        instance_list = [
            SdsXmlConservationInstance(
                generalisation=element.get("generalisation", ""),
                zone=element.get("zone"),
                data_resource_id=element.get("dataResourceId"),
                authority=element.get("authority"),
                category=element.get("category"),
            )
            for element in species.findall("./instances/conservationInstance")
        ]
        if species.get("guid"):
            by_taxon_id.setdefault(species.get("guid", ""), []).extend(instance_list)
        if species.get("name"):
            by_name.setdefault(_name_key(species.get("name", "")), []).extend(instance_list)
    return {"by_taxon_id": by_taxon_id, "by_name": by_name}


def load_sds_csv_rules(
    csv_path: str | Path,
) -> dict[str, dict[str, list[SdsXmlConservationInstance]]]:
    """Load Swedish restricted-species CSV rows as generalisation rules."""
    by_taxon_id: dict[str, list[SdsXmlConservationInstance]] = {}
    by_name: dict[str, list[SdsXmlConservationInstance]] = {}
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            generalisation = str(row.get("generalisation") or "").strip()
            if not generalisation:
                continue
            instance = SdsXmlConservationInstance(
                generalisation=generalisation,
                zone=None,
                data_resource_id=None,
                authority=None,
                category=None,
            )
            for field in ("taxonID", "id", "guid"):
                taxon_id = str(row.get(field) or "").strip()
                if taxon_id:
                    by_taxon_id.setdefault(taxon_id, []).append(instance)
            for field in ("scientificName", "Supplied Name"):
                name = str(row.get(field) or "").strip()
                if name:
                    by_name.setdefault(_name_key(name), []).append(instance)
    return {"by_taxon_id": by_taxon_id, "by_name": by_name}


def _matching_sds_xml_instances(
    rules: Mapping[str, Mapping[str, list[SdsXmlConservationInstance]]],
    *,
    scientific_name: str | None,
    taxon_id: str | None,
    data_resource_id: str | None,
    zone: str | None,
) -> list[SdsXmlConservationInstance]:
    """Select XML instances using SDS's taxon, resource, and zone constraints."""
    candidates = rules["by_taxon_id"].get(taxon_id, []) if taxon_id else []
    if not candidates and scientific_name:
        candidates = rules["by_name"].get(_name_key(scientific_name), [])
    return [
        item
        for item in candidates
        if (not data_resource_id or item.data_resource_id in (None, "", data_resource_id))
        and (not item.zone or item.zone == zone)
    ]


def sds_generalization_ala(
    df: pd.DataFrame,
    xml_path: str | Path | None = None,
    *,
    rules_csv_path: str | Path | None = None,
    rules: dict[str, dict[str, list[SdsXmlConservationInstance]]] | None = None,
    scientific_name_col: str = "scientificName",
    taxon_id_col: str | None = "taxonId",
    data_resource_id_col: str | None = "dataResourceId",
    zone_col: str | None = "zone",
    zone: str | None = None,
    latitude_col: str = "decimalLatitude",
    longitude_col: str = "decimalLongitude",
    data_generalizations_col: str = "dataGeneralizations",
    information_withheld_col: str = "informationWithheld",
) -> pd.DataFrame:
    """Apply ALA/SDS generalisation from XML or a restricted-species CSV.

    A rule scoped to a zone is applied only when the caller supplies that
    record's already-determined zone, either through ``zone_col`` or ``zone``.
    The CSV form uses its ``generalisation`` field and has no zone or resource
    scoping. When multiple rules match, the most restrictive rule wins.
    """
    if rules is None:
        if rules_csv_path is not None and xml_path is not None:
            raise ValueError("Provide either 'xml_path' or 'rules_csv_path', not both.")
        if rules_csv_path is not None:
            rules = load_sds_csv_rules(rules_csv_path)
        elif xml_path is not None:
            rules = load_sds_xml_rules(xml_path)
        else:
            raise ValueError("Provide 'xml_path', 'rules_csv_path', or preloaded 'rules'.")
    df = df.copy()
    if latitude_col not in df.columns or longitude_col not in df.columns:
        logging.warning("Latitude or longitude column missing; skipping SDS XML generalization.")
        return df
    # SDS GeneralisationRule returns display-ready decimal strings. Preserve its
    # trailing-zero precision without assigning strings into float columns.
    df[latitude_col] = df[latitude_col].astype(object)
    df[longitude_col] = df[longitude_col].astype(object)
    for col in (data_generalizations_col, information_withheld_col):
        if col not in df.columns:
            df[col] = ""

    transformed_count = 0
    withheld_count = 0
    for idx in df.index:
        taxon_id = (
            str(df.at[idx, taxon_id_col]).strip()
            if taxon_id_col and taxon_id_col in df.columns and pd.notna(df.at[idx, taxon_id_col])
            else None
        )
        name = (
            str(df.at[idx, scientific_name_col]).strip()
            if scientific_name_col in df.columns and pd.notna(df.at[idx, scientific_name_col])
            else None
        )
        resource = (
            str(df.at[idx, data_resource_id_col]).strip()
            if data_resource_id_col and data_resource_id_col in df.columns and pd.notna(df.at[idx, data_resource_id_col])
            else None
        )
        row_zone = zone
        if row_zone is None and zone_col and zone_col in df.columns and pd.notna(df.at[idx, zone_col]):
            row_zone = str(df.at[idx, zone_col]).strip() or None
        instances = _matching_sds_xml_instances(
            rules,
            scientific_name=name,
            taxon_id=taxon_id,
            data_resource_id=resource,
            zone=row_zone,
        )
        if not instances:
            continue
        instance = max(instances, key=lambda item: sds_generalisation_metres(item.generalisation))
        is_withheld = instance.generalisation.upper() == "WITHHOLD"
        try:
            generalized_lat, generalized_lon = sds_generalise_coordinates(
                float(df.at[idx, latitude_col]),
                float(df.at[idx, longitude_col]),
                instance.generalisation,
            )
        except (TypeError, ValueError):
            continue
        df.at[idx, latitude_col], df.at[idx, longitude_col] = generalized_lat, generalized_lon
        if is_withheld:
            withheld_count += 1
        else:
            transformed_count += 1
        existing = df.at[idx, data_generalizations_col]
        statement = f"Coordinates generalized using SDS rule {instance.generalisation}."
        df.at[idx, data_generalizations_col] = " ".join(
            part for part in ("" if pd.isna(existing) else str(existing).strip(), statement) if part
        )
        if instance.generalisation.upper() == "WITHHOLD":
            existing = df.at[idx, information_withheld_col]
            df.at[idx, information_withheld_col] = " ".join(
                part
                for part in (
                    "" if pd.isna(existing) else str(existing).strip(),
                    "Precise original coordinates withheld.",
                )
                if part
            )
    logging.info(
        "Sensitive species transformation completed [ALA]: %s rows transformed, "
        "%s rows withheld, %s rows unchanged.",
        transformed_count,
        withheld_count,
        len(df) - transformed_count - withheld_count,
    )
    return df


def sds_generalization_gbif(
    df: pd.DataFrame,
    rules_path: str | Path | None = None,
    *,
    rules: dict[str, dict[str, str]] | None = None,
    scientific_name_col: str = "scientificName",
    latitude_col: str = "decimalLatitude",
    longitude_col: str = "decimalLongitude",
    uncertainty_col: str = "coordinateUncertaintyInMeters",
    data_generalizations_col: str = "dataGeneralizations",
    information_withheld_col: str = "informationWithheld",
) -> pd.DataFrame:
    """Apply GBIF guide decimal-grid policy to a public DataFrame derivative.

    The policy is a restriction list: taxa without a matching rule retain
    their source coordinates unchanged. An explicit ``not_sensitive`` rule
    likewise keeps coordinates unrestricted. Expired rules and ``extreme``
    rules have their public coordinates suppressed pending review or
    restricted access.
    """
    if rules is None:
        if rules_path is None:
            raise ValueError("Either 'rules' or 'rules_path' is required for sds_generalization_gbif.")
        rules = load_gbif_generalization_rules(rules_path)
    df = df.copy()
    required = {scientific_name_col, latitude_col, longitude_col, uncertainty_col}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(
            "GBIF generalization requires columns: " + ", ".join(sorted(missing))
        )
    output_columns = {
        data_generalizations_col: "",
        information_withheld_col: "",
        "coordinatePrecision": "",
        "sensitive": False,
        "sensitivityCategory": "",
        "sensitivityReason": "",
        "sensitivityReviewDate": "",
        "originalCoordinatePrecision": "",
    }
    for column, default in output_columns.items():
        if column not in df.columns:
            df[column] = default

    status_counts: dict[str, int] = {}
    for idx in df.index:
        try:
            result = gbif_generalize_observation(
                str(df.at[idx, scientific_name_col]),
                float(df.at[idx, latitude_col]),
                float(df.at[idx, longitude_col]),
                rules=rules,
                original_uncertainty_m=float(df.at[idx, uncertainty_col]),
            )
        except (TypeError, ValueError):
            # Invalid source rows are withheld rather than accidentally
            # released by a sensitive-data transformation.
            result = {
                "status": "invalid_record_review",
                "informationWithheld": "Coordinates withheld pending source-record review.",
            }

        status = result["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == "generalized":
            df.at[idx, latitude_col] = result["decimalLatitude"]
            df.at[idx, longitude_col] = result["decimalLongitude"]
            df.at[idx, uncertainty_col] = result["coordinateUncertaintyInMeters"]
            df.at[idx, "coordinatePrecision"] = result["coordinatePrecision"]
        elif status not in {"not_sensitive", "not_listed_public"}:
            df.at[idx, latitude_col] = pd.NA
            df.at[idx, longitude_col] = pd.NA

        for column in (
            "sensitive",
            "sensitivityCategory",
            "sensitivityReason",
            "sensitivityReviewDate",
            "originalCoordinatePrecision",
        ):
            if column in result:
                df.at[idx, column] = result[column]
        for column, key in (
            (data_generalizations_col, "dataGeneralizations"),
            (information_withheld_col, "informationWithheld"),
        ):
            if key not in result:
                continue
            existing = "" if pd.isna(df.at[idx, column]) else str(df.at[idx, column]).strip()
            df.at[idx, column] = " ".join(
                part for part in (existing, result[key]) if part
            )

    logging.info(
        "Sensitive species transformation completed [GBIF]: %s rows transformed, "
        "%s rows withheld, %s rows unchanged.",
        status_counts.get("generalized", 0),
        sum(
            status_counts.get(status, 0)
            for status in (
                "coordinates_suppressed",
                "sensitivity_review_due",
                "invalid_record_review",
            )
        ),
        status_counts.get("not_sensitive", 0)
        + status_counts.get("not_listed_public", 0),
    )
    return df


def get_diffusion_values(protection_level: int) -> tuple[int, int]:
    """Return the SOS grid modulus and offset for a protection level.

    Unknown levels deliberately retain SOS's no-generalization fallback of a
    one metre grid with a zero offset.
    """
    return _DIFFUSION_VALUES.get(int(protection_level), (1, 0))


def load_sos_sensitivity_rules(
    rules_path: str | Path,
    generalisation_to_protection_level: Mapping[str, int] | None = None,
) -> dict[str, dict[str, int]]:
    """Load Swedish restricted-species rules for SOS protection levels.

    The source CSV defines taxa and generalisation distances. The mapping from
    those distances to SOS protection levels is explicit and configurable so
    the SOS transformation remains independent of ALA XML rule data.
    """
    mapping = {
        str(key).strip().casefold(): int(value)
        for key, value in (
            generalisation_to_protection_level or _DEFAULT_SOS_LEVEL_BY_GENERALISATION
        ).items()
    }
    if not set(mapping.values()).issubset(_DIFFUSION_VALUES):
        raise ValueError("SOS protection levels must be one of 2, 3, 4, or 5")

    by_taxon_id: dict[str, int] = {}
    by_name: dict[str, int] = {}
    with Path(rules_path).open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            generalisation = str(row.get("generalisation") or "").strip().casefold()
            level = mapping.get(generalisation)
            if level is None:
                continue
            taxon_id = str(row.get("taxonID") or row.get("id") or "").strip()
            if taxon_id:
                by_taxon_id[taxon_id] = max(level, by_taxon_id.get(taxon_id, level))
            for field in ("scientificName", "Supplied Name", "name"):
                name = str(row.get(field) or "").strip()
                if name:
                    key = _name_key(name)
                    by_name[key] = max(level, by_name.get(key, level))
    return {"by_taxon_id": by_taxon_id, "by_name": by_name}


def _sos_protection_level(
    rules: Mapping[str, Mapping[str, int]], taxon_id: str | None, scientific_name: str | None
) -> int | None:
    """Find the most specific configured SOS level for one occurrence."""
    if taxon_id:
        level = rules["by_taxon_id"].get(taxon_id)
        if level is not None:
            return level
    return rules["by_name"].get(_name_key(scientific_name)) if scientific_name else None


def diffuse_coordinates(
    lat: float,
    lon: float,
    protection_level: int,
    uncertainty_in_meters: float | None = None,
) -> dict[str, Any]:
    """Diffuse a WGS84 coordinate using the SOS protection-level grid.

    This is a direct implementation of SOS diffusion: each projected
    coordinate is snapped to the lower grid edge and shifted by its
    level-specific offset.
    """
    latitude, longitude = float(lat), float(lon)
    if not (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        raise ValueError("Coordinates must be finite WGS84 latitude/longitude")

    mod, add = get_diffusion_values(protection_level)
    easting, northing = _project_wgs84_to_sweref99(longitude, latitude)
    diffused_easting = easting - (easting % mod) + add
    diffused_northing = northing - (northing % mod) + add
    diffused_lon, diffused_lat = _project_sweref99_to_wgs84(
        diffused_easting, diffused_northing
    )

    uncertainty = 0.0 if uncertainty_in_meters is None else float(uncertainty_in_meters)
    if not math.isfinite(uncertainty):
        raise ValueError("Uncertainty must be finite")

    return {
        "original_wgs84": (latitude, longitude),
        "original_sweref99tm": (easting, northing),
        "protection_level": int(protection_level),
        "diffusion_mod": mod,
        "diffusion_add": add,
        "diffused_sweref99tm": (diffused_easting, diffused_northing),
        "diffused_wgs84": (diffused_lat, diffused_lon),
        "coordinate_uncertainty_in_meters": max(uncertainty, float(mod)),
    }


def _web_mercator_from_wgs84(lon: float, lat: float) -> tuple[float, float]:
    """Project WGS84 coordinates to EPSG:3857 without requiring pyproj."""
    radius = 6_378_137.0
    lat = max(min(lat, 85.0511287798066), -85.0511287798066)
    return (
        radius * math.radians(lon),
        radius * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)),
    )


def _wgs84_from_web_mercator(x: float, y: float) -> tuple[float, float]:
    """Project EPSG:3857 coordinates to WGS84 without requiring pyproj."""
    radius = 6_378_137.0
    return (
        math.degrees(x / radius),
        math.degrees(2 * math.atan(math.exp(y / radius)) - math.pi / 2),
    )


def create_diffused_coordinate_info(
    lat: float,
    lon: float,
    protection_level: int,
    diffusion_coordinate_system: str = "web_mercator",
) -> dict[str, Any]:
    """Port SOS ``CoordinateDiffusionManager``'s comparison calculation.

    ``web_mercator`` follows that manager's default mode and applies its SOS
    offset. ``sweref99_tm`` follows its alternate diagnostic mode, which uses
    the cell centre. This utility is diagnostic only; production observation
    diffusion remains :func:`diffuse_coordinates` and uses SWEREF99 TM + SOS
    offsets, as in SOS ``DiffusionManager``.
    """
    latitude, longitude = float(lat), float(lon)
    if not (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        raise ValueError("Coordinates must be finite WGS84 latitude/longitude")

    mod, add = get_diffusion_values(protection_level)
    original_sweref = _project_wgs84_to_sweref99(longitude, latitude)
    original_web_mercator = _web_mercator_from_wgs84(longitude, latitude)
    mode = diffusion_coordinate_system.casefold()
    if mode == "web_mercator":
        x, y = original_web_mercator
        diffused_web_mercator = (x - x % mod + add, y - y % mod + add)
        diffused_lon, diffused_lat = _wgs84_from_web_mercator(*diffused_web_mercator)
        diffused_sweref = _project_wgs84_to_sweref99(diffused_lon, diffused_lat)
    elif mode == "sweref99_tm":
        x, y = original_sweref
        diffused_sweref = (x - x % mod + mod / 2, y - y % mod + mod / 2)
        diffused_lon, diffused_lat = _project_sweref99_to_wgs84(*diffused_sweref)
        diffused_web_mercator = _web_mercator_from_wgs84(diffused_lon, diffused_lat)
    else:
        raise ValueError("diffusion_coordinate_system must be 'web_mercator' or 'sweref99_tm'")

    return {
        "protectionLevel": int(protection_level),
        "originalPointWgs84": (latitude, longitude),
        "originalPointSweref99Tm": original_sweref,
        "originalPointWebMercator": original_web_mercator,
        "diffusedPointWgs84": (diffused_lat, diffused_lon),
        "diffusedPointSweref99Tm": diffused_sweref,
        "diffusedPointWebMercator": diffused_web_mercator,
        "distanceBetweenOriginalAndDiffusedSweref99Tm": math.dist(
            original_sweref, diffused_sweref
        ),
    }


def calculate_coordinate_diffusion_stats(
    sample_size: int = 100_000,
    diffusion_coordinate_system: str = "web_mercator",
    random_seed: int | None = None,
) -> dict[int, dict[str, int]]:
    """Port SOS diagnostic diffusion statistics for protection levels 2-5."""
    if sample_size < 1:
        raise ValueError("sample_size must be positive")
    generator = random.Random(random_seed)
    stats: dict[int, dict[str, int]] = {}
    for level in range(2, 6):
        results = []
        for _ in range(sample_size):
            # Mirrors CoordinateDiffusionManager.CreateCoordinateInSweden().
            latitude = generator.uniform(56, 57)
            longitude = generator.uniform(12, 19)
            results.append(
                create_diffused_coordinate_info(
                    latitude, longitude, level, diffusion_coordinate_system
                )
            )
        distances = [item["distanceBetweenOriginalAndDiffusedSweref99Tm"] for item in results]
        stats[level] = {
            "protectionLevel": level,
            "minDistance": int(min(distances)),
            "maxDistance": int(max(distances)),
            "avgDistance": int(sum(distances) / len(distances)),
            "nrOriginalDistinctCoordinates": len(
                {tuple(map(int, item["originalPointSweref99Tm"])) for item in results}
            ),
            "nrDiffusedDistinctCoordinates": len(
                {tuple(map(int, item["diffusedPointSweref99Tm"])) for item in results}
            ),
        }
    return stats


def _month_start(value: Any) -> Any:
    """Reduce a date/datetime value to its month, as SOS DiffusionManager does."""
    if isinstance(value, datetime):
        return datetime(value.year, value.month, 1)
    if isinstance(value, date):
        return date(value.year, value.month, 1)
    return value


def _date_interval(start: Any, end: Any) -> str:
    """Provide a Darwin Core-style interval for supported date values."""
    def format_date(value: Any) -> str:
        return value.isoformat() if isinstance(value, (date, datetime)) else ""

    start_text, end_text = format_date(start), format_date(end)
    return "/".join(part for part in (start_text, end_text) if part)


def diffuse_observation(observation: dict[str, Any]) -> dict[str, Any]:
    """Diffuse an SOS-shaped observation and remove exact-location metadata.

    This mirrors the record-level behaviour of the SOS reference utility.  It
    is useful to callers handling nested SOS payloads; ETL tables should use
    :func:`sds_diffusion_sos` instead.
    """
    obs = dict(observation)
    location = dict(obs.get("location") or {})
    occurrence = dict(obs.get("occurrence") or {})
    event = dict(obs.get("event") or {})
    artportalen_internal = dict(obs.get("artportalenInternal") or {})
    lat = location.get("decimalLatitude")
    lon = location.get("decimalLongitude")
    level = occurrence.get("sensitivityCategory", 0)

    for field in (
        "decimalLatitude",
        "decimalLongitude",
        "countryRegion",
        "county",
        "locality",
        "municipality",
        "parish",
        "province",
        "verbatimCoordinates",
        "verbatimLatitude",
        "verbatimLongitude",
        "verbatimLocality",
        "point",
        "pointLocation",
        "pointWithBuffer",
        "pointWithDisturbanceBuffer",
    ):
        location[field] = None
    attributes = dict(location.get("attributes") or {})
    attributes["externalId"] = None
    attributes["verbatimMunicipality"] = None
    attributes["verbatimProvince"] = None
    location["attributes"] = attributes

    try:
        valid_coordinate = float(lat) != 0 and float(lon) != 0
        result = diffuse_coordinates(
            float(lat),
            float(lon),
            int(level),
            location.get("coordinateUncertaintyInMeters", 0),
        )
    except (TypeError, ValueError, OverflowError):
        valid_coordinate = False

    if valid_coordinate:
        location["decimalLatitude"], location["decimalLongitude"] = result[
            "diffused_wgs84"
        ]
        location["coordinateUncertaintyInMeters"] = result[
            "coordinate_uncertainty_in_meters"
        ]

    for field in ("reportedBy", "recordedBy", "occurrenceRemarks"):
        if field in occurrence:
            occurrence[field] = ""

    for field in (
        "birdValidationAreaIds",
        "locationPresentationNameParishRegion",
        "parentLocality",
        "parentLocationId",
        "reportedByUserId",
        "occurrenceRecordedByInternal",
    ):
        artportalen_internal[field] = None
    artportalen_internal["reportedByUserAlias"] = ""

    if "modified" in obs:
        obs["modified"] = _month_start(obs["modified"])
    if "reportedDate" in occurrence:
        occurrence["reportedDate"] = _month_start(occurrence["reportedDate"])
    if "startDate" in event:
        event["startDate"] = _month_start(event["startDate"])
    if "endDate" in event:
        event["endDate"] = _month_start(event["endDate"])
    if event:
        event["verbatimEventDate"] = _date_interval(
            event.get("startDate"), event.get("endDate")
        )

    existing = str(obs.get("dataGeneralizations") or "").strip()
    statement = (
        "All data related to the exact location of the observation has been "
        "diffused or removed. Native data is available with extended privileges."
    )
    obs["location"] = location
    obs["occurrence"] = occurrence
    if event:
        obs["event"] = event
    if obs.get("artportalenInternal") is not None:
        obs["artportalenInternal"] = artportalen_internal
    obs["accessRights"] = "FreeUsage"
    obs["sensitive"] = False
    obs["diffusionStatus"] = "DiffusedBySystem"
    obs["dataGeneralizations"] = " ".join(
        part for part in (existing, statement) if part
    )
    return obs


def sds_diffusion_sos(
    df: pd.DataFrame,
    sensitivity_category_col: str = "sensitivityCategory",
    rules_path: str | Path | None = None,
    rules: dict[str, dict[str, int]] | None = None,
    generalisation_to_protection_level: Mapping[str, int] | None = None,
    scientific_name_col: str = "scientificName",
    taxon_id_col: str | None = "taxonID",
    latitude_col: str = "decimalLatitude",
    longitude_col: str = "decimalLongitude",
    uncertainty_col: str = "coordinateUncertaintyInMeters",
    data_generalizations_col: str = "dataGeneralizations",
    diffusion_status_col: str = "diffusionStatus",
) -> pd.DataFrame:
    """Apply SOS coordinate diffusion to tabular Darwin Core observations.

    Rows with a valid SOS level from 2 through 5 are diffused. Levels can come
    directly from ``sensitivity_category_col`` or, when ``rules_path`` is
    supplied, from the Swedish restricted-species CSV and an explicit
    generalisation-to-level mapping. Rows without a level are unchanged.
    """
    df = df.copy()
    required = {latitude_col, longitude_col}
    if not required.issubset(df.columns):
        logging.warning(
            "Latitude or longitude column missing; skipping SOS diffusion."
        )
        return df
    if rules is None and rules_path is not None:
        rules = load_sos_sensitivity_rules(
            rules_path, generalisation_to_protection_level
        )
    if sensitivity_category_col not in df.columns:
        df[sensitivity_category_col] = pd.NA

    if uncertainty_col not in df.columns:
        df[uncertainty_col] = ""
    if data_generalizations_col not in df.columns:
        df[data_generalizations_col] = ""
    if diffusion_status_col not in df.columns:
        df[diffusion_status_col] = ""

    diffused_count = 0
    for idx in df.index:
        try:
            lat = float(df.at[idx, latitude_col])
            lon = float(df.at[idx, longitude_col])
        except (TypeError, ValueError, OverflowError):
            continue
        raw_level = df.at[idx, sensitivity_category_col]
        try:
            level = None if pd.isna(raw_level) else int(raw_level)
        except (TypeError, ValueError, OverflowError):
            level = None
        if level is None and rules is not None:
            taxon_id = (
                str(df.at[idx, taxon_id_col]).strip()
                if taxon_id_col
                and taxon_id_col in df.columns
                and pd.notna(df.at[idx, taxon_id_col])
                else None
            )
            scientific_name = (
                str(df.at[idx, scientific_name_col]).strip()
                if scientific_name_col in df.columns
                and pd.notna(df.at[idx, scientific_name_col])
                else None
            )
            level = _sos_protection_level(rules, taxon_id, scientific_name)
            if level is not None:
                df.at[idx, sensitivity_category_col] = level
        if level not in _DIFFUSION_VALUES or not (math.isfinite(lat) and math.isfinite(lon)):
            continue

        raw_uncertainty = df.at[idx, uncertainty_col]
        try:
            uncertainty = 0.0 if pd.isna(raw_uncertainty) else float(raw_uncertainty)
        except (TypeError, ValueError):
            uncertainty = 0.0

        try:
            result = diffuse_coordinates(lat, lon, level, uncertainty)
        except ValueError:
            continue

        df.at[idx, latitude_col], df.at[idx, longitude_col] = result["diffused_wgs84"]
        df.at[idx, uncertainty_col] = result["coordinate_uncertainty_in_meters"]
        existing = df.at[idx, data_generalizations_col]
        existing_text = "" if pd.isna(existing) else str(existing).strip()
        statement = (
            "All data related to the exact location of the observation has been "
            "diffused or removed."
        )
        df.at[idx, data_generalizations_col] = " ".join(
            part for part in (existing_text, statement) if part
        )
        df.at[idx, diffusion_status_col] = "DiffusedBySystem"
        diffused_count += 1

    logging.info(
        "Sensitive species transformation completed [SOS]: %s rows transformed, "
        "0 rows withheld, %s rows unchanged.",
        diffused_count,
        len(df) - diffused_count,
    )
    return df

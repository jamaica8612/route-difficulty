"""Core data collection and aggregation for the route-difficulty dataset.

The browser never imports this module. Public API credentials are read only by the
offline builder, and all published payloads contain normalized facts and source
metadata rather than raw API responses.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


APT_SIDO_CODES = ("11", "26", "27", "28", "29", "30", "31", "36", "41", "43", "44", "45", "46", "47", "48", "50", "51", "52")
TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}
TRANSIENT_API_CODES = {"05", "22", "23"}
POSTCODE_ALIASES = ("우편번호", "postcode", "zipno", "zip_no", "bas_id", "districtno")
ROAD_ADDRESS_ALIASES = ("도로명주소", "roadaddress", "road_addr", "rn_addr", "fullroadaddr", "newplatplc")


class PipelineError(RuntimeError):
    pass


class RequestBudgetReached(PipelineError):
    pass


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temp, path)


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8", newline="\n") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
        output.flush()
        os.fsync(output.fileno())
    return count


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise PipelineError(f"Invalid JSONL at {path}:{line_number}: {error}") from error
            if isinstance(value, dict):
                yield value


def completed_keys(path: Path, key: str) -> set[str]:
    return {str(row.get(key)) for row in iter_jsonl(path) if row.get(key) is not None}


def normalize_address(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def nullable_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def sum_known(*values: Any) -> int | None:
    parsed = [nullable_int(value) for value in values]
    known = [value for value in parsed if value is not None]
    return sum(known) if known else None


def percentage(known: int, total: int) -> int | None:
    return round(known / total * 100) if total else None


def housing_type(record: dict[str, Any]) -> str:
    purpose = f"{record.get('mainPurpsCdNm') or ''} {record.get('etcPurps') or ''}".replace(" ", "")
    if "아파트" in purpose:
        return "apartment"
    if "연립주택" in purpose or "다세대주택" in purpose:
        return "villa"
    if "오피스텔" in purpose:
        return "officetel"
    if "단독주택" in purpose or "다가구주택" in purpose:
        return "detached"
    return "other"


def is_residential(record: dict[str, Any]) -> bool:
    return housing_type(record) != "other"


def building_facts(record: dict[str, Any], source: str = "BUILDING_HUB") -> dict[str, Any]:
    households = nullable_int(record.get("hhldCnt"))
    if households is None:
        households = nullable_int(record.get("fmlyCnt"))
    if households is None:
        households = nullable_int(record.get("hoCnt"))
    return {
        "id": str(record.get("mgmBldrgstPk") or record.get("kaptCode") or hashlib.sha1(str(record).encode()).hexdigest()),
        "name": str(record.get("bldNm") or record.get("kaptName") or record.get("dongNm") or "").strip(),
        "address": str(record.get("newPlatPlc") or record.get("doroJuso") or record.get("platPlc") or "").strip(),
        "source": source,
        "groundFloors": nullable_int(record.get("grndFlrCnt") if source == "BUILDING_HUB" else record.get("ktownFlrNo")),
        "elevators": nullable_int(record.get("rideUseElvtCnt") if source == "BUILDING_HUB" else record.get("kaptdEcnt")),
        "households": households if source == "BUILDING_HUB" else nullable_int(record.get("kaptdaCnt")),
        "parkingSpaces": sum_known(
            record.get("indrMechUtcnt"), record.get("oudrMechUtcnt"), record.get("indrAutoUtcnt"), record.get("oudrAutoUtcnt")
        ) if source == "BUILDING_HUB" else sum_known(record.get("kaptdPcnt"), record.get("kaptdPcntu")),
        "buildingCount": None if source == "BUILDING_HUB" else nullable_int(record.get("kaptDongCnt")),
        "housingType": housing_type(record) if source == "BUILDING_HUB" else "apartment",
    }


def attention_tags(facts: dict[str, Any]) -> list[dict[str, str]]:
    tags: list[dict[str, str]] = []
    floors = facts.get("groundFloors")
    elevators = facts.get("elevators")
    households = facts.get("households")
    parking = facts.get("parkingSpaces")
    buildings = facts.get("buildingCount")
    if floors is not None and floors >= 4 and elevators == 0:
        tags.append({
            "code": "NO_ELEVATOR_4F_PLUS",
            "label": "승강기 0대·지상 4층 이상",
            "evidence": f"지상 {floors}층 / 승객용 승강기 0대",
        })
    if households is not None and households > 0 and parking is not None and parking / households < 0.5:
        tags.append({
            "code": "LOW_PARKING_RATIO",
            "label": "세대 대비 등록 주차 0.5 미만",
            "evidence": f"{households}세대 / 등록 주차 {parking}대",
        })
    if buildings is not None and buildings >= 5:
        tags.append({
            "code": "LARGE_COMPLEX",
            "label": "5개 동 이상 공동주택",
            "evidence": f"공식 단지정보 {buildings}개 동",
        })
    return tags


@dataclass
class RequestBudget:
    path: Path
    daily_limit: int = 4500

    def __post_init__(self) -> None:
        self.day = date.today().isoformat()
        self.count = 0
        if self.path.exists():
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if state.get("day") == self.day:
                self.count = int(state.get("count") or 0)

    def consume(self) -> None:
        if self.count >= self.daily_limit:
            raise RequestBudgetReached(f"Daily public-data request budget reached ({self.daily_limit})")
        self.count += 1
        atomic_write_json(self.path, {"day": self.day, "count": self.count})


class PublicDataClient:
    def __init__(self, service_key: str, cache_dir: Path, budget: RequestBudget, timeout: int = 40) -> None:
        if not service_key:
            raise PipelineError("PUBLIC_DATA_SERVICE_KEY is required")
        self.service_key = urllib.parse.unquote(service_key)
        self.cache_dir = cache_dir
        self.budget = budget
        self.timeout = timeout

    def fetch(self, endpoint: str, operation: str, params: dict[str, Any], source: str) -> dict[str, Any]:
        clean_params = {key: value for key, value in params.items() if value is not None and value != ""}
        cache_key = hashlib.sha256(json.dumps([endpoint, operation, clean_params], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cache_path = self.cache_dir / source / f"{cache_key}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))

        query = urllib.parse.urlencode({"serviceKey": self.service_key, **clean_params})
        url = f"{endpoint.rstrip('/')}/{operation}?{query}"
        last_error: Exception | None = None
        for attempt in range(4):
            self.budget.consume()
            try:
                request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "route-difficulty-builder/1.0"})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8-sig"))
                header = payload.get("response", {}).get("header", {})
                result_code = str(header.get("resultCode") or "00")
                if result_code != "00":
                    message = str(header.get("resultMsg") or result_code)
                    if result_code in TRANSIENT_API_CODES and attempt < 3:
                        time.sleep(2 ** attempt)
                        continue
                    raise PipelineError(f"{source} API error {result_code}: {message}")
                atomic_write_json(cache_path, payload)
                return payload
            except urllib.error.HTTPError as error:
                last_error = error
                if error.code not in TRANSIENT_HTTP_CODES or attempt >= 3:
                    raise PipelineError(f"{source} HTTP {error.code}") from error
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                last_error = error
                if attempt >= 3:
                    raise PipelineError(f"{source} request failed: {error}") from error
            time.sleep(2 ** attempt)
        raise PipelineError(f"{source} request failed: {last_error}")


def response_page(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    body = payload.get("response", {}).get("body") or {}
    items = body.get("items")
    if isinstance(items, dict):
        items = items.get("item")
    if items is None:
        items = body.get("item")
    if items is None:
        normalized: list[dict[str, Any]] = []
    elif isinstance(items, list):
        normalized = [item for item in items if isinstance(item, dict)]
    elif isinstance(items, dict):
        normalized = [items]
    else:
        normalized = []
    return normalized, int(body.get("totalCount") or len(normalized))


def _normalized_columns(row: dict[str, Any]) -> dict[str, Any]:
    return {re.sub(r"[^0-9a-z가-힣]", "", str(key).strip().lower()): value for key, value in row.items()}


def _pick(row: dict[str, Any], aliases: Iterable[str]) -> Any:
    normalized = _normalized_columns(row)
    for alias in aliases:
        key = re.sub(r"[^0-9a-z가-힣]", "", alias.lower())
        if key in normalized and normalized[key] not in (None, ""):
            return normalized[key]
    return None


def _digits(value: Any, width: int | None = None, take_last: bool = False) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if take_last and width and len(digits) > width:
        digits = digits[-width:]
    if width and digits:
        digits = digits.zfill(width)
    return digits


def road_key_from_row(row: dict[str, Any]) -> str | None:
    road_code = _digits(_pick(row, ("naRoadCd", "도로명코드", "roadCd", "rnCd")), 12)
    sigungu = _digits(_pick(row, ("sigunguCd", "시군구코드", "sigCd")), 5)
    if not sigungu and len(road_code) >= 5:
        sigungu = road_code[:5]
    bjdong = _digits(_pick(row, ("naBjdongCd", "도로명주소법정동코드", "법정동코드", "bjdongCd")), 5, take_last=True)
    underground = _digits(_pick(row, ("naUgrndCd", "지하여부", "ugrndCd")), 1) or "0"
    main = _digits(_pick(row, ("naMainBun", "건물번호본번", "mainBun")), 5)
    sub = _digits(_pick(row, ("naSubBun", "건물번호부번", "subBun")), 5) or "00000"
    if not all((sigungu, road_code, main)):
        return None
    return "|".join((sigungu, road_code, bjdong, underground, main, sub))


def constructed_road_address(row: dict[str, Any]) -> str:
    direct = _pick(row, ROAD_ADDRESS_ALIASES)
    if direct:
        return str(direct)
    sido = _pick(row, ("시도", "sido", "ctpvNm")) or ""
    sigungu = _pick(row, ("시군구", "sigungu", "sigNm")) or ""
    eupmyeon = _pick(row, ("읍면", "읍면동", "eupmyeon", "emdNm")) or ""
    road = _pick(row, ("도로명", "roadName", "rn")) or ""
    main = _digits(_pick(row, ("건물번호본번", "naMainBun", "mainBun")))
    sub = _digits(_pick(row, ("건물번호부번", "naSubBun", "subBun")))
    number = f"{int(main)}" if main else ""
    if sub and int(sub):
        number += f"-{int(sub)}"
    return " ".join(str(value).strip() for value in (sido, sigungu, eupmyeon, road, number) if str(value).strip())


def _open_csv(path: Path):
    sample_bytes = path.read_bytes()[:65536]
    encoding = "utf-8-sig"
    for candidate in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            sample = sample_bytes.decode(candidate)
            encoding = candidate
            break
        except UnicodeDecodeError:
            continue
    delimiter = "|" if sample.count("|") > sample.count(",") else ","
    handle = path.open(encoding=encoding, newline="")
    return handle, csv.DictReader(handle, delimiter=delimiter)


class AddressIndex:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection = sqlite3.connect(path)

    def close(self) -> None:
        self.connection.close()

    def lookup(self, record: dict[str, Any]) -> str | None:
        key = road_key_from_row(record)
        if key:
            row = self.connection.execute("select postcode from road_keys where road_key = ?", (key,)).fetchone()
            if row and row[0]:
                return str(row[0])
        for address in (record.get("doroJuso"), record.get("newPlatPlc"), record.get("kaptAddr"), record.get("platPlc")):
            normalized = normalize_address(address)
            if not normalized:
                continue
            row = self.connection.execute("select postcode from addresses where normalized_address = ?", (normalized,)).fetchone()
            if row and row[0]:
                return str(row[0])
        explicit = _digits(record.get("zipcode"), 5)
        return explicit if len(explicit) == 5 else None


def build_address_index(paths: list[Path], database_path: Path, legal_dong_path: Path) -> dict[str, int]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = database_path.with_name(f".{database_path.name}.tmp-{os.getpid()}")
    if temp_path.exists():
        temp_path.unlink()
    connection = sqlite3.connect(temp_path)
    connection.executescript("""
        pragma journal_mode = WAL;
        pragma synchronous = NORMAL;
        create table road_keys (road_key text primary key, postcode text not null);
        create table addresses (normalized_address text primary key, postcode text);
        create table legal_dongs (sigungu_cd text not null, bjdong_cd text not null, primary key(sigungu_cd, bjdong_cd));
    """)
    stats = {"rows": 0, "roadKeys": 0, "addresses": 0, "invalidPostcodes": 0}
    for path in paths:
        handle, reader = _open_csv(path)
        with handle:
            for raw_row in reader:
                stats["rows"] += 1
                postcode = _digits(_pick(raw_row, POSTCODE_ALIASES), 5)
                if len(postcode) != 5:
                    stats["invalidPostcodes"] += 1
                    continue
                key = road_key_from_row(raw_row)
                if key:
                    before = connection.total_changes
                    connection.execute("insert or ignore into road_keys values (?, ?)", (key, postcode))
                    stats["roadKeys"] += connection.total_changes - before
                address = normalize_address(constructed_road_address(raw_row))
                if address:
                    connection.execute("""
                        insert into addresses values (?, ?)
                        on conflict(normalized_address) do update set postcode =
                          case when addresses.postcode = excluded.postcode then addresses.postcode else null end
                    """, (address, postcode))
                    stats["addresses"] += 1
                road_code = _digits(_pick(raw_row, ("도로명코드", "naRoadCd", "roadCd")), 12)
                sigungu = _digits(_pick(raw_row, ("시군구코드", "sigunguCd", "sigCd")), 5) or road_code[:5]
                bjdong = _digits(_pick(raw_row, ("법정동코드", "bjdongCd", "naBjdongCd")), 5, take_last=True)
                if sigungu and bjdong:
                    connection.execute("insert or ignore into legal_dongs values (?, ?)", (sigungu, bjdong))
                if stats["rows"] % 100_000 == 0:
                    connection.commit()
    connection.commit()
    legal_dong_path.parent.mkdir(parents=True, exist_ok=True)
    with legal_dong_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(("sigunguCd", "bjdongCd"))
        writer.writerows(connection.execute("select sigungu_cd, bjdong_cd from legal_dongs order by 1, 2"))
    connection.close()
    os.replace(temp_path, database_path)
    return stats


def read_legal_dongs(path: Path) -> list[tuple[str, str]]:
    handle, reader = _open_csv(path)
    values: set[tuple[str, str]] = set()
    with handle:
        for row in reader:
            sigungu = _digits(_pick(row, ("sigunguCd", "시군구코드")), 5)
            bjdong = _digits(_pick(row, ("bjdongCd", "법정동코드")), 5, take_last=True)
            if sigungu and bjdong:
                values.add((sigungu, bjdong))
    return sorted(values)


def default_accumulator(base: dict[str, Any]) -> dict[str, Any]:
    return {
        "base": base,
        "total": 0,
        "residential": 0,
        "households": 0,
        "housingTypes": {"apartment": 0, "villa": 0, "officetel": 0, "detached": 0},
        "floorsKnown": 0,
        "elevatorsKnown": 0,
        "zeroElevators": 0,
        "parkingKnown": 0,
        "parkingSpaces": 0,
        "parkingHouseholds": 0,
        "matched": 0,
        "attention": {},
    }


def add_attention(accumulator: dict[str, Any], facts: dict[str, Any]) -> None:
    tags = attention_tags(facts)
    if not tags:
        return
    candidate = {key: value for key, value in facts.items() if key != "housingType"}
    candidate["tags"] = tags
    key = normalize_address(candidate.get("address")) or candidate["id"]
    existing = accumulator["attention"].get(key)
    if existing:
        tags_by_code = {tag["code"]: tag for tag in existing["tags"]}
        tags_by_code.update({tag["code"]: tag for tag in tags})
        existing["tags"] = list(tags_by_code.values())
        for field in ("name", "groundFloors", "elevators", "households", "parkingSpaces", "buildingCount"):
            if existing.get(field) in (None, "") and candidate.get(field) not in (None, ""):
                existing[field] = candidate[field]
        if candidate["source"] == "K_APT":
            existing["source"] = "K_APT"
        return
    accumulator["attention"][key] = candidate


def add_building_record(accumulator: dict[str, Any], record: dict[str, Any]) -> None:
    facts = building_facts(record)
    accumulator["total"] += 1
    accumulator["matched"] += 1
    if is_residential(record):
        accumulator["residential"] += 1
    households = facts["households"]
    if households is not None:
        accumulator["households"] += households
        kind = facts["housingType"]
        if kind in accumulator["housingTypes"]:
            accumulator["housingTypes"][kind] += households
    if facts["groundFloors"] is not None:
        accumulator["floorsKnown"] += 1
    if facts["elevators"] is not None:
        accumulator["elevatorsKnown"] += 1
        if facts["elevators"] == 0:
            accumulator["zeroElevators"] += 1
    if facts["parkingSpaces"] is not None:
        accumulator["parkingKnown"] += 1
        accumulator["parkingSpaces"] += facts["parkingSpaces"]
        if households is not None and households > 0:
            accumulator["parkingHouseholds"] += households
    add_attention(accumulator, facts)


def add_kapt_record(accumulator: dict[str, Any], record: dict[str, Any]) -> None:
    merged = {**(record.get("list") or {}), **(record.get("basic") or {}), **(record.get("detail") or {})}
    add_attention(accumulator, building_facts(merged, source="K_APT"))


def _attention_sort_key(building: dict[str, Any]) -> tuple[int, int, str]:
    priorities = {"NO_ELEVATOR_4F_PLUS": 0, "LOW_PARKING_RATIO": 1, "LARGE_COMPLEX": 2}
    priority = min((priorities.get(tag.get("code"), 9) for tag in building.get("tags", [])), default=9)
    return priority, -(building.get("groundFloors") or 0), str(building.get("name") or building.get("address") or "")


def finalize_zone(accumulator: dict[str, Any], generated_at: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    total = accumulator["total"]
    attention = sorted(accumulator["attention"].values(), key=_attention_sort_key)
    base = accumulator["base"]
    parking_households = accumulator["parkingHouseholds"]
    return {
        "schemaVersion": 1,
        "postcode": base["postcode"],
        "region": base.get("region") or {},
        "geometry": base["geometry"],
        "areaM2": base.get("areaM2"),
        "summary": {
            "buildings": {"total": total, "residential": accumulator["residential"]},
            "households": {"total": accumulator["households"]},
            "housingTypes": {
                "apartmentHouseholds": accumulator["housingTypes"]["apartment"],
                "villaHouseholds": accumulator["housingTypes"]["villa"],
                "officetelHouseholds": accumulator["housingTypes"]["officetel"],
                "detachedHouseholds": accumulator["housingTypes"]["detached"],
            },
            "floors": {"knownBuildings": accumulator["floorsKnown"]},
            "elevators": {"knownBuildings": accumulator["elevatorsKnown"], "zeroBuildings": accumulator["zeroElevators"]},
            "parking": {
                "knownBuildings": accumulator["parkingKnown"],
                "totalSpaces": accumulator["parkingSpaces"],
                "spacesPerHousehold": round(accumulator["parkingSpaces"] / parking_households, 2) if parking_households else None,
            },
        },
        "coverage": {
            "addressMatchedCount": accumulator["matched"],
            "unmatchedCount": None,
            "floorsKnownPercent": percentage(accumulator["floorsKnown"], total),
            "elevatorsKnownPercent": percentage(accumulator["elevatorsKnown"], total),
            "parkingKnownPercent": percentage(accumulator["parkingKnown"], total),
        },
        "attentionBuildings": attention[:30],
        "attentionOmittedCount": max(0, len(attention) - 30),
        "sources": sources,
        "generatedAt": generated_at,
    }


def _find_postcode(properties: dict[str, Any]) -> str | None:
    value = _pick(properties, ("BAS_ID", "basId", "postcode", "우편번호", "districtNo"))
    postcode = _digits(value, 5)
    return postcode if len(postcode) == 5 else None


def _region(properties: dict[str, Any]) -> dict[str, str | None]:
    return {
        "sido": _pick(properties, ("CTP_KOR_NM", "ctpvNm", "sido", "시도명")),
        "sigungu": _pick(properties, ("SIG_KOR_NM", "sigNm", "sigungu", "시군구명")),
        "eupmyeondong": _pick(properties, ("EMD_KOR_NM", "emdNm", "eupmyeondong", "읍면동명")),
    }


def _geometry_dependencies():
    try:
        import shapefile  # type: ignore
        from pyproj import Transformer  # type: ignore
        from shapely.geometry import mapping, shape  # type: ignore
        from shapely.ops import transform  # type: ignore
    except ImportError as error:
        raise PipelineError("Boundary processing requires: pip install -r scripts/requirements-data.txt") from error
    return shapefile, Transformer, mapping, shape, transform


def iter_boundaries(path: Path, source_crs: str = "EPSG:5179") -> Iterator[dict[str, Any]]:
    """Yield postcode polygons in WGS84 from GeoJSON or TL_KODIS_BAS shapefile."""
    shapefile, Transformer, mapping, shape, transform = _geometry_dependencies()
    to_wgs84 = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True).transform
    to_area = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True).transform
    if path.suffix.lower() in {".json", ".geojson"}:
        payload = json.loads(path.read_text(encoding="utf-8"))
        features = payload.get("features") if payload.get("type") == "FeatureCollection" else [payload]
        for feature in features:
            properties = feature.get("properties") or {}
            postcode = _find_postcode(properties)
            if not postcode or not feature.get("geometry"):
                continue
            geometry = shape(feature["geometry"])
            area_geometry = transform(to_area, geometry) if source_crs.upper() == "EPSG:4326" else geometry
            wgs_geometry = geometry if source_crs.upper() == "EPSG:4326" else transform(to_wgs84, geometry)
            if not wgs_geometry.is_valid:
                wgs_geometry = wgs_geometry.buffer(0)
            yield {
                "postcode": postcode,
                "region": _region(properties),
                "geometry": mapping(wgs_geometry),
                "areaM2": round(area_geometry.area, 1),
            }
        return

    if path.suffix.lower() != ".shp":
        raise PipelineError(f"Unsupported boundary format: {path}")
    reader = shapefile.Reader(str(path), encoding="cp949")
    field_names = [field[0] for field in reader.fields[1:]]
    for shape_record in reader.iterShapeRecords():
        properties = dict(zip(field_names, shape_record.record, strict=False))
        postcode = _find_postcode(properties)
        if not postcode:
            continue
        geometry = shape(shape_record.shape.__geo_interface__)
        area = round(geometry.area, 1)
        geometry = geometry.simplify(0.8, preserve_topology=True)
        wgs_geometry = transform(to_wgs84, geometry)
        if not wgs_geometry.is_valid:
            wgs_geometry = wgs_geometry.buffer(0)
        yield {
            "postcode": postcode,
            "region": _region(properties),
            "geometry": mapping(wgs_geometry),
            "areaM2": area,
        }


def build_dataset(
    boundary_path: Path,
    address_index_path: Path,
    building_records_path: Path,
    apt_details_path: Path,
    output_root: Path,
    version: str,
    source_crs: str = "EPSG:5179",
    source_dates: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise PipelineError("Dataset version contains unsupported characters")
    generated_at = utc_now().isoformat()
    accumulators = {item["postcode"]: default_accumulator(item) for item in iter_boundaries(boundary_path, source_crs)}
    if not accumulators:
        raise PipelineError("No postcode boundaries were found")

    address_index = AddressIndex(address_index_path)
    unmatched_buildings = 0
    matched_buildings = 0
    for record in iter_jsonl(building_records_path):
        postcode = address_index.lookup(record)
        accumulator = accumulators.get(postcode or "")
        if not accumulator:
            unmatched_buildings += 1
            continue
        matched_buildings += 1
        add_building_record(accumulator, record)

    unmatched_apt = 0
    matched_apt = 0
    for record in iter_jsonl(apt_details_path):
        merged = {**(record.get("list") or {}), **(record.get("basic") or {})}
        postcode = address_index.lookup(merged)
        accumulator = accumulators.get(postcode or "")
        if not accumulator:
            unmatched_apt += 1
            continue
        matched_apt += 1
        add_kapt_record(accumulator, record)
    address_index.close()

    source_dates = source_dates or {}
    sources = [
        {"name": "주소기반산업지원서비스 기초구역", "url": "https://business.juso.go.kr/", "referenceDate": source_dates.get("postcodeBoundaries")},
        {"name": "국토교통부 건축HUB 건축물대장", "url": "https://www.data.go.kr/data/15134735/openapi.do", "referenceDate": source_dates.get("buildingRegister")},
        {"name": "국토교통부 공동주택 기본정보", "url": "https://www.data.go.kr/data/15058453/openapi.do", "referenceDate": source_dates.get("kApt")},
    ]
    releases = output_root / "releases"
    staging = releases / f".staging-{version}-{os.getpid()}"
    final_release = releases / version
    if final_release.exists():
        raise PipelineError(f"Dataset release already exists: {final_release}")
    for postcode, accumulator in accumulators.items():
        zone = finalize_zone(accumulator, generated_at, sources)
        atomic_write_json(staging / "zones" / postcode[:2] / f"{postcode}.json", zone)

    release_validation = validate_release(staging, expected_count=len(accumulators))
    releases.mkdir(parents=True, exist_ok=True)
    os.replace(staging, final_release)
    manifest = {
        "schemaVersion": 1,
        "datasetVersion": version,
        "generatedAt": generated_at,
        "zoneCount": len(accumulators),
        "sourceDates": source_dates,
        "coverage": {
            "buildingMatchedCount": matched_buildings,
            "buildingUnmatchedCount": unmatched_buildings,
            "kAptMatchedCount": matched_apt,
            "kAptUnmatchedCount": unmatched_apt,
        },
        "validation": release_validation,
        "status": "ready",
    }
    atomic_write_json(output_root / "manifest.json", manifest)
    return manifest


def validate_zone(zone: dict[str, Any], expected_postcode: str | None = None) -> list[str]:
    errors: list[str] = []
    postcode = str(zone.get("postcode") or "")
    if not re.fullmatch(r"\d{5}", postcode):
        errors.append("invalid postcode")
    if expected_postcode and postcode != expected_postcode:
        errors.append("postcode does not match file name")
    if zone.get("geometry", {}).get("type") not in {"Polygon", "MultiPolygon"}:
        errors.append("invalid geometry type")
    if not isinstance(zone.get("attentionBuildings"), list) or len(zone.get("attentionBuildings", [])) > 30:
        errors.append("attention list must contain at most 30 entries")
    for building in zone.get("attentionBuildings") or []:
        tag_codes = {tag.get("code") for tag in building.get("tags") or []}
        if "NO_ELEVATOR_4F_PLUS" in tag_codes and not (building.get("elevators") == 0 and (building.get("groundFloors") or 0) >= 4):
            errors.append(f"invalid no-elevator tag on {building.get('id')}")
        if "LOW_PARKING_RATIO" in tag_codes:
            households = building.get("households")
            parking = building.get("parkingSpaces")
            if not (households and parking is not None and parking / households < 0.5):
                errors.append(f"invalid parking tag on {building.get('id')}")
        if "LARGE_COMPLEX" in tag_codes and (building.get("buildingCount") or 0) < 5:
            errors.append(f"invalid large-complex tag on {building.get('id')}")
    return errors


def validate_release(release_dir: Path, expected_count: int | None = None) -> dict[str, Any]:
    zone_files = list((release_dir / "zones").glob("[0-9][0-9]/[0-9][0-9][0-9][0-9][0-9].json"))
    errors: list[str] = []
    seen: set[str] = set()
    for path in zone_files:
        raw = path.read_text(encoding="utf-8")
        if "serviceKey" in raw or "PUBLIC_DATA_SERVICE_KEY" in raw:
            errors.append(f"credential marker in {path}")
            continue
        zone = json.loads(raw)
        postcode = path.stem
        if postcode in seen:
            errors.append(f"duplicate postcode {postcode}")
        seen.add(postcode)
        errors.extend(f"{postcode}: {message}" for message in validate_zone(zone, postcode))
    if expected_count is not None and len(zone_files) != expected_count:
        errors.append(f"zone count {len(zone_files)} != expected {expected_count}")
    if errors:
        raise PipelineError("Dataset validation failed:\n" + "\n".join(errors[:50]))
    return {"zoneFiles": len(zone_files), "errors": 0}


def validate_published_dataset(output_root: Path) -> dict[str, Any]:
    manifest_path = output_root / "manifest.json"
    if not manifest_path.exists():
        raise PipelineError(f"Manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = str(manifest.get("datasetVersion") or "")
    result = validate_release(output_root / "releases" / version, int(manifest.get("zoneCount") or 0))
    return {"datasetVersion": version, **result}

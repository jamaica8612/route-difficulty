#!/usr/bin/env python3
"""Collect public data and publish versioned postcode-zone JSON files."""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from pipeline_core import (
    APT_SIDO_CODES,
    PipelineError,
    PublicDataClient,
    RequestBudget,
    RequestBudgetReached,
    append_jsonl,
    atomic_write_json,
    build_address_index,
    build_dataset,
    completed_keys,
    iter_jsonl,
    load_env,
    read_legal_dongs,
    response_page,
    validate_published_dataset,
)


ROOT = Path(__file__).resolve().parents[1]


def settings() -> dict[str, str]:
    values = load_env(ROOT / ".env")
    values.update({key: value for key, value in os.environ.items() if value})
    return values


def data_paths(values: dict[str, str]) -> tuple[Path, Path, Path]:
    input_dir = Path(values.get("ROUTE_DATA_INPUT_DIR", ROOT / "data/input")).resolve()
    work_dir = Path(values.get("ROUTE_DATA_WORK_DIR", ROOT / "data/work")).resolve()
    output_dir = Path(values.get("ROUTE_DATA_OUTPUT_DIR", ROOT / "public/data")).resolve()
    return input_dir, work_dir, output_dir


def make_client(values: dict[str, str], work_dir: Path) -> PublicDataClient:
    budget = RequestBudget(
        work_dir / "state" / "request-budget.json",
        int(values.get("PUBLIC_DATA_DAILY_REQUEST_LIMIT", "4500")),
    )
    return PublicDataClient(values.get("PUBLIC_DATA_SERVICE_KEY", ""), work_dir / "cache", budget)


def read_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def collect_apt_list(client: PublicDataClient, endpoint: str, output: Path, state_path: Path, sido_codes: list[str], page_size: int, max_pages: int | None = None) -> dict:
    state = read_state(state_path)
    if state.get("completed") and not max_pages:
        return state
    existing = completed_keys(output, "kaptCode")
    start_index = int(state.get("sidoIndex") or 0)
    start_page = int(state.get("page") or 1)
    pages = 0
    for sido_index in range(start_index, len(sido_codes)):
        sido = sido_codes[sido_index]
        page = start_page if sido_index == start_index else 1
        while True:
            payload = client.fetch(endpoint, "getSidoAptList3", {
                "sidoCode": sido,
                "pageNo": page,
                "numOfRows": page_size,
            }, "apt-list")
            items, total = response_page(payload)
            append_jsonl(output, (item for item in items if str(item.get("kaptCode")) not in existing))
            existing.update(str(item.get("kaptCode")) for item in items if item.get("kaptCode"))
            pages += 1
            next_state = {"completed": False, "sidoIndex": sido_index, "sidoCode": sido, "page": page + 1, "records": len(existing)}
            atomic_write_json(state_path, next_state)
            if page * page_size >= total or not items:
                break
            if max_pages and pages >= max_pages:
                return next_state
            page += 1
        start_page = 1
        atomic_write_json(state_path, {"completed": False, "sidoIndex": sido_index + 1, "page": 1, "records": len(existing)})
        if max_pages and pages >= max_pages:
            return read_state(state_path)
    final = {"completed": True, "sidoIndex": len(sido_codes), "page": 1, "records": len(existing)}
    atomic_write_json(state_path, final)
    return final


def _single_item(client: PublicDataClient, endpoint: str, operation: str, kapt_code: str) -> dict | None:
    payload = client.fetch(endpoint, operation, {"kaptCode": kapt_code}, f"apt-{operation}")
    items, _ = response_page(payload)
    return items[0] if items else None


def collect_apt_details(client: PublicDataClient, endpoint: str, apt_list_path: Path, output: Path, state_path: Path, max_records: int | None = None) -> dict:
    existing = completed_keys(output, "kaptCode")
    processed = 0
    total = 0
    for list_record in iter_jsonl(apt_list_path):
        kapt_code = str(list_record.get("kaptCode") or "")
        if not kapt_code:
            continue
        total += 1
        if kapt_code in existing:
            continue
        basic = _single_item(client, endpoint, "getAphusBassInfoV4", kapt_code)
        detail = _single_item(client, endpoint, "getAphusDtlInfoV4", kapt_code)
        append_jsonl(output, [{"kaptCode": kapt_code, "list": list_record, "basic": basic, "detail": detail}])
        existing.add(kapt_code)
        processed += 1
        atomic_write_json(state_path, {"completed": False, "records": len(existing), "lastKaptCode": kapt_code})
        if max_records and processed >= max_records:
            return read_state(state_path)
    final = {"completed": len(existing) >= total, "records": len(existing), "expectedRecords": total}
    atomic_write_json(state_path, final)
    return final


def collect_building_hub(client: PublicDataClient, endpoint: str, legal_dong_path: Path, output: Path, state_path: Path, page_size: int, max_pages: int | None = None) -> dict:
    legal_dongs = read_legal_dongs(legal_dong_path)
    state = read_state(state_path)
    if state.get("completed") and not max_pages:
        return state
    existing = completed_keys(output, "mgmBldrgstPk")
    start_index = int(state.get("legalDongIndex") or 0)
    start_page = int(state.get("page") or 1)
    pages = 0
    for dong_index in range(start_index, len(legal_dongs)):
        sigungu, bjdong = legal_dongs[dong_index]
        page = start_page if dong_index == start_index else 1
        while True:
            payload = client.fetch(endpoint, "getBrTitleInfo", {
                "sigunguCd": sigungu,
                "bjdongCd": bjdong,
                "pageNo": page,
                "numOfRows": page_size,
                "_type": "json",
            }, "building-hub")
            items, total = response_page(payload)
            new_items = [item for item in items if str(item.get("mgmBldrgstPk")) not in existing]
            append_jsonl(output, new_items)
            existing.update(str(item.get("mgmBldrgstPk")) for item in new_items if item.get("mgmBldrgstPk"))
            pages += 1
            next_state = {
                "completed": False,
                "legalDongIndex": dong_index,
                "sigunguCd": sigungu,
                "bjdongCd": bjdong,
                "page": page + 1,
                "records": len(existing),
            }
            atomic_write_json(state_path, next_state)
            if page * page_size >= total or not items:
                break
            if max_pages and pages >= max_pages:
                return next_state
            page += 1
        start_page = 1
        atomic_write_json(state_path, {"completed": False, "legalDongIndex": dong_index + 1, "page": 1, "records": len(existing)})
        if max_pages and pages >= max_pages:
            return read_state(state_path)
    final = {"completed": True, "legalDongIndex": len(legal_dongs), "page": 1, "records": len(existing)}
    atomic_write_json(state_path, final)
    return final


def address_files(input_dir: Path, values: dict[str, str]) -> list[Path]:
    pattern = values.get("ROUTE_ADDRESS_DB_GLOB", str(input_dir / "address" / "**" / "*.*"))
    candidates = [Path(path) for path in sorted(glob.glob(pattern, recursive=True))]
    return [path.resolve() for path in candidates if path.is_file() and path.suffix.lower() in {".csv", ".txt"}]


def resolve_boundary(input_dir: Path, values: dict[str, str]) -> Path:
    configured = values.get("ROUTE_BOUNDARY_FILE")
    if configured:
        return Path(configured).resolve()
    matches = list(input_dir.rglob("TL_KODIS_BAS.shp")) + list(input_dir.rglob("*postcode*.geojson"))
    if not matches:
        raise PipelineError(f"TL_KODIS_BAS boundary file is missing under {input_dir}")
    return matches[0].resolve()


def prepare_addresses(input_dir: Path, work_dir: Path, values: dict[str, str]) -> dict:
    files = address_files(input_dir, values)
    if not files:
        raise PipelineError(f"Address DB CSV/TXT files are missing under {input_dir / 'address'}")
    index_path = work_dir / "address-index.sqlite3"
    legal_dongs = work_dir / "legal-dongs.csv"
    newest_input = max(path.stat().st_mtime for path in files)
    if index_path.exists() and legal_dongs.exists() and index_path.stat().st_mtime >= newest_input:
        return {"cached": True, "files": len(files)}
    return build_address_index(files, index_path, legal_dongs)


def run_build(
    input_dir: Path,
    work_dir: Path,
    output_dir: Path,
    values: dict[str, str],
    version: str | None,
    source_crs: str,
) -> dict:
    boundary = resolve_boundary(input_dir, values)
    version = version or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    collection_date = datetime.now(timezone.utc).date().isoformat()
    boundary_date = datetime.fromtimestamp(boundary.stat().st_mtime, timezone.utc).date().isoformat()
    source_dates = {
        "postcodeBoundaries": values.get("ROUTE_POSTCODE_SOURCE_DATE") or boundary_date,
        "buildingRegister": values.get("ROUTE_BUILDING_SOURCE_DATE") or collection_date,
        "kApt": values.get("ROUTE_KAPT_SOURCE_DATE") or collection_date,
    }
    return build_dataset(
        boundary,
        work_dir / "address-index.sqlite3",
        work_dir / "raw" / "building-hub.jsonl",
        work_dir / "raw" / "apt-details.jsonl",
        output_dir,
        version,
        source_crs,
        source_dates,
    )


def run_monthly(values: dict[str, str], input_dir: Path, work_dir: Path, output_dir: Path) -> dict:
    cycle = datetime.now(timezone.utc).strftime("%Y-%m")
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("datasetVersion") == cycle and manifest.get("status") == "ready":
            return {"status": "already-current", "datasetVersion": cycle}

    # A monthly directory keeps raw API responses and checkpoints immutable after
    # publication. The next month therefore starts a fresh collection while an
    # interrupted run in the current month resumes exactly where it stopped.
    cycle_work = work_dir / "cycles" / cycle
    prepare_addresses(input_dir, cycle_work, values)
    client = make_client(values, cycle_work)
    apt_list_state = collect_apt_list(
        client,
        values.get("PUBLIC_DATA_APT_LIST_ENDPOINT", "https://apis.data.go.kr/1613000/AptListService3"),
        cycle_work / "raw" / "apt-list.jsonl",
        cycle_work / "state" / "apt-list.json",
        list(APT_SIDO_CODES),
        500,
    )
    apt_details_state = collect_apt_details(
        client,
        values.get("PUBLIC_DATA_APT_BASIS_ENDPOINT", "https://apis.data.go.kr/1613000/AptBasisInfoServiceV4"),
        cycle_work / "raw" / "apt-list.jsonl",
        cycle_work / "raw" / "apt-details.jsonl",
        cycle_work / "state" / "apt-details.json",
    )
    building_state = collect_building_hub(
        client,
        values.get("PUBLIC_DATA_BUILDING_HUB_ENDPOINT", "https://apis.data.go.kr/1613000/BldRgstHubService"),
        cycle_work / "legal-dongs.csv",
        cycle_work / "raw" / "building-hub.jsonl",
        cycle_work / "state" / "building-hub.json",
        1000,
    )
    if not all(state.get("completed") for state in (apt_list_state, apt_details_state, building_state)):
        raise RequestBudgetReached("Collection is incomplete and will resume on the next scheduled run")
    return run_build(
        input_dir,
        cycle_work,
        output_dir,
        values,
        cycle,
        values.get("ROUTE_BOUNDARY_CRS", "EPSG:5179"),
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare-address-index")
    apt = commands.add_parser("collect-apt-list")
    apt.add_argument("--sido-codes", default=",".join(APT_SIDO_CODES))
    apt.add_argument("--page-size", type=int, default=500)
    apt.add_argument("--max-pages", type=int)
    details = commands.add_parser("collect-apt-details")
    details.add_argument("--max-records", type=int)
    buildings = commands.add_parser("collect-building-hub")
    buildings.add_argument("--page-size", type=int, default=1000)
    buildings.add_argument("--max-pages", type=int)
    build = commands.add_parser("build")
    build.add_argument("--version")
    build.add_argument("--source-crs", default="EPSG:5179")
    commands.add_parser("validate")
    commands.add_parser("monthly")
    return root


def main() -> int:
    args = parser().parse_args()
    values = settings()
    input_dir, work_dir, output_dir = data_paths(values)
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "prepare-address-index":
            result = prepare_addresses(input_dir, work_dir, values)
        elif args.command == "collect-apt-list":
            client = make_client(values, work_dir)
            result = collect_apt_list(client, values.get("PUBLIC_DATA_APT_LIST_ENDPOINT", "https://apis.data.go.kr/1613000/AptListService3"), work_dir / "raw/apt-list.jsonl", work_dir / "state/apt-list.json", args.sido_codes.split(","), args.page_size, args.max_pages)
        elif args.command == "collect-apt-details":
            client = make_client(values, work_dir)
            result = collect_apt_details(client, values.get("PUBLIC_DATA_APT_BASIS_ENDPOINT", "https://apis.data.go.kr/1613000/AptBasisInfoServiceV4"), work_dir / "raw/apt-list.jsonl", work_dir / "raw/apt-details.jsonl", work_dir / "state/apt-details.json", args.max_records)
        elif args.command == "collect-building-hub":
            client = make_client(values, work_dir)
            result = collect_building_hub(client, values.get("PUBLIC_DATA_BUILDING_HUB_ENDPOINT", "https://apis.data.go.kr/1613000/BldRgstHubService"), work_dir / "legal-dongs.csv", work_dir / "raw/building-hub.jsonl", work_dir / "state/building-hub.json", args.page_size, args.max_pages)
        elif args.command == "build":
            result = run_build(input_dir, work_dir, output_dir, values, args.version, args.source_crs)
        elif args.command == "validate":
            result = validate_published_dataset(output_dir)
        else:
            result = run_monthly(values, input_dir, work_dir, output_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except RequestBudgetReached as error:
        print(f"RESUME_NEEDED: {error}", file=sys.stderr)
        return 75
    except PipelineError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

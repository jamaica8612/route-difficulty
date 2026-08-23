import csv
import json
from datetime import datetime, timezone
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from pipeline_core import (  # noqa: E402
    AddressIndex,
    add_building_record,
    attention_tags,
    build_address_index,
    build_dataset,
    building_facts,
    default_accumulator,
    finalize_zone,
    housing_type,
    normalize_address,
    validate_published_dataset,
)
from build_dataset import run_monthly  # noqa: E402


class PipelineCoreTests(unittest.TestCase):
    def test_monthly_run_does_not_rebuild_current_release(self):
        cycle = datetime.now(timezone.utc).strftime("%Y-%m")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            (output / "manifest.json").write_text(
                json.dumps({"datasetVersion": cycle, "status": "ready"}),
                encoding="utf-8",
            )
            result = run_monthly({}, root / "input", root / "work", output)
            self.assertEqual(result, {"status": "already-current", "datasetVersion": cycle})

    def test_null_and_zero_elevator_are_distinct(self):
        missing = building_facts({"mgmBldrgstPk": "missing", "grndFlrCnt": 5})
        zero = building_facts({"mgmBldrgstPk": "zero", "grndFlrCnt": 5, "rideUseElvtCnt": 0})
        self.assertIsNone(missing["elevators"])
        self.assertEqual(zero["elevators"], 0)
        self.assertEqual(attention_tags(missing), [])
        self.assertEqual(attention_tags(zero)[0]["code"], "NO_ELEVATOR_4F_PLUS")

    def test_attention_rules_are_transparent(self):
        facts = {
            "groundFloors": 6,
            "elevators": 0,
            "households": 20,
            "parkingSpaces": 8,
            "buildingCount": 5,
        }
        self.assertEqual(
            [tag["code"] for tag in attention_tags(facts)],
            ["NO_ELEVATOR_4F_PLUS", "LOW_PARKING_RATIO", "LARGE_COMPLEX"],
        )

    def test_housing_type_classification(self):
        self.assertEqual(housing_type({"mainPurpsCdNm": "공동주택(다세대주택)"}), "villa")
        self.assertEqual(housing_type({"etcPurps": "업무시설(오피스텔)"}), "officetel")
        self.assertEqual(housing_type({"mainPurpsCdNm": "제2종근린생활시설"}), "other")

    def test_zone_aggregation_uses_only_known_values(self):
        base = {"postcode": "47502", "geometry": {"type": "Polygon", "coordinates": []}, "region": {}, "areaM2": 10}
        accumulator = default_accumulator(base)
        add_building_record(accumulator, {
            "mgmBldrgstPk": "one", "mainPurpsCdNm": "아파트", "hhldCnt": 10,
            "grndFlrCnt": 5, "rideUseElvtCnt": 0, "indrAutoUtcnt": 2,
        })
        add_building_record(accumulator, {"mgmBldrgstPk": "two", "mainPurpsCdNm": "근린생활시설"})
        zone = finalize_zone(accumulator, "2026-08-23T00:00:00Z", [])
        self.assertEqual(zone["summary"]["buildings"], {"total": 2, "residential": 1})
        self.assertEqual(zone["summary"]["households"]["total"], 10)
        self.assertEqual(zone["coverage"]["elevatorsKnownPercent"], 50)
        self.assertIsNone(zone["coverage"]["unmatchedCount"])

    def test_address_index_matches_road_key_and_normalized_address(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            address_csv = root / "address.csv"
            with address_csv.open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=["우편번호", "시도", "시군구", "도로명코드", "도로명", "지하여부", "건물번호본번", "건물번호부번", "법정동코드"])
                writer.writeheader()
                writer.writerow({"우편번호": "47502", "시도": "부산광역시", "시군구": "연제구", "도로명코드": "264703130001", "도로명": "법원북로", "지하여부": "0", "건물번호본번": "33", "건물번호부번": "0", "법정동코드": "2647010200"})
            database = root / "addresses.sqlite3"
            build_address_index([address_csv], database, root / "legal.csv")
            index = AddressIndex(database)
            self.assertEqual(index.lookup({"sigunguCd": "26470", "naRoadCd": "264703130001", "naBjdongCd": "10200", "naUgrndCd": "0", "naMainBun": "33", "naSubBun": "0"}), "47502")
            self.assertEqual(index.lookup({"doroJuso": "부산광역시 연제구 법원북로 33"}), "47502")
            index.close()
            self.assertEqual(normalize_address("부산 (연산동) 법원북로 33"), "부산법원북로33")

    def test_end_to_end_build_and_validate_with_geojson(self):
        try:
            import shapely  # noqa: F401
        except ImportError:
            self.skipTest("data geometry dependencies are not installed")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            boundary = root / "postcode.geojson"
            boundary.write_text(json.dumps({
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {"BAS_ID": "47502", "CTP_KOR_NM": "부산광역시", "SIG_KOR_NM": "연제구"},
                    "geometry": {"type": "Polygon", "coordinates": [[[129.07, 35.18], [129.08, 35.18], [129.08, 35.19], [129.07, 35.18]]]},
                }],
            }), encoding="utf-8")
            address_csv = root / "address.csv"
            with address_csv.open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=["우편번호", "도로명주소"])
                writer.writeheader()
                writer.writerow({"우편번호": "47502", "도로명주소": "부산광역시 연제구 법원북로 33"})
            database = root / "addresses.sqlite3"
            build_address_index([address_csv], database, root / "legal.csv")
            buildings = root / "buildings.jsonl"
            buildings.write_text(json.dumps({"mgmBldrgstPk": "sample", "newPlatPlc": "부산광역시 연제구 법원북로 33", "mainPurpsCdNm": "다세대주택", "grndFlrCnt": 5, "rideUseElvtCnt": 0, "hhldCnt": 12}) + "\n", encoding="utf-8")
            apt = root / "apt.jsonl"
            apt.write_text("", encoding="utf-8")
            output = root / "public-data"
            manifest = build_dataset(boundary, database, buildings, apt, output, "test-v1", "EPSG:4326")
            self.assertEqual(manifest["zoneCount"], 1)
            result = validate_published_dataset(output)
            self.assertEqual(result["zoneFiles"], 1)
            zone = json.loads((output / "releases/test-v1/zones/47/47502.json").read_text(encoding="utf-8"))
            self.assertEqual(zone["attentionBuildings"][0]["tags"][0]["code"], "NO_ELEVATOR_4F_PLUS")


if __name__ == "__main__":
    unittest.main()

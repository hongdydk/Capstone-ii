"""휴게소·공영차고지 전체 주소를 지오코딩하여 각각 JSON 파일에 저장합니다.

실행:
    cd C:/CapstoneII
    .venv\\Scripts\\python.exe backend/scripts/build_poi_caches.py

결과 파일:
    backend/rest_stops_cache.json   — 휴게소
    backend/truck_yards_cache.json  — 공영차고지

각 파일 구조:
    [
        {"name": "문막(인천)", "address": "강원도 ...", "lat": 37.12, "lon": 127.34},
        ...
    ]
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv
load_dotenv(ROOT / "backend" / ".env", override=True)

import xlrd
from app.services.tmap_service import geocode_address
from scripts._direction_utils import parse_name_direction

XLS_REST  = ROOT / "자료" / "휴게소정보_260325.xls"
XLS_YARD  = ROOT / "자료" / "공영차고지정보_260325.xls"

OUT_REST  = ROOT / "backend" / "rest_stops_cache.json"
OUT_YARD  = ROOT / "backend" / "truck_yards_cache.json"


def _load_xls(path: Path, name_col: int, addr_col: int) -> list[dict]:
    wb = xlrd.open_workbook(str(path))
    ws = wb.sheet_by_index(0)
    rows = []
    for r in range(1, ws.nrows):
        name = str(ws.cell_value(r, name_col)).strip()
        addr = str(ws.cell_value(r, addr_col)).strip()
        if name and addr:
            rows.append({"name": name, "address": addr})
    return rows


def _add_direction(results: list[dict]) -> list[dict]:
    """휴게소 목록의 각 항목에 direction 필드를 추가합니다."""
    for item in results:
        item["direction"] = parse_name_direction(item["name"])
    return results


async def _geocode_all(items: list[dict], label: str) -> list[dict]:
    sem     = asyncio.Semaphore(5)
    results = []
    fail    = 0

    async def _one(item: dict) -> None:
        nonlocal fail
        async with sem:
            coord = await geocode_address(item["address"])
        if coord:
            results.append({
                "name":      item["name"],
                "address":   item["address"],
                "lat":       coord[0],
                "lon":       coord[1],
                "direction": parse_name_direction(item["name"]),
            })
        else:
            fail += 1
            print(f"  [실패] {item['name']} / {item['address']}")

    tasks = [_one(item) for item in items]
    await asyncio.gather(*tasks)

    print(f"  {label}: 성공 {len(results)}/{len(items)}개 / 실패 {fail}개")
    return results


async def run() -> None:
    # XLS 로드
    rest_items = _load_xls(XLS_REST, name_col=3, addr_col=5)
    yard_items = _load_xls(XLS_YARD, name_col=2, addr_col=3)

    print(f"휴게소 {len(rest_items)}개 / 공영차고지 {len(yard_items)}개 지오코딩 시작\n")

    # 지오코딩
    rest_data = await _geocode_all(rest_items, "휴게소")
    yard_data = await _geocode_all(yard_items, "공영차고지")

    # 방향 정보 추가 (이미 _one에서 삽입됨; 기존 캐시 보완 시 여기서 재적용)
    rest_data.sort(key=lambda x: x["name"])
    yard_data.sort(key=lambda x: x["name"])

    # 통계
    n_up   = sum(1 for r in rest_data if r.get("direction") == "상행")
    n_down = sum(1 for r in rest_data if r.get("direction") == "하행")
    n_none = sum(1 for r in rest_data if r.get("direction") is None)
    print(f"\n휴게소 방향 분류: 상행 {n_up}개 / 하행 {n_down}개 / 미분류 {n_none}개")

    # JSON 저장
    OUT_REST.write_text(
        json.dumps(rest_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    OUT_YARD.write_text(
        json.dumps(yard_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n저장 완료:")
    print(f"  휴게소     → {OUT_REST}  ({len(rest_data)}개)")
    print(f"  공영차고지 → {OUT_YARD}  ({len(yard_data)}개)")


if __name__ == "__main__":
    asyncio.run(run())

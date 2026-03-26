"""한국도로공사 공공데이터 API → 휴게소 방향 포함 JSON 캐시 빌드

API 문서: 자료/Rest.txt
API 엔드포인트: https://data.ex.co.kr/openapi/locationinfo/locationinfoRest

사전 준비:
    data.ex.co.kr 에서 API 키 발급 후 아래 명령어로 실행:

실행:
    cd C:/CapstoneII
    .venv\\Scripts\\python.exe backend/scripts/fetch_ex_rest_stops.py --key YOUR_KEY

옵션:
    --key       한국도로공사 공공데이터 API 인증키 (필수)
    --rows      페이지당 건수 (기본 1000, 최대 9999)
    --out       출력 파일 경로 (기본 backend/ex_rest_stops_cache.json)

출력 포맷:
    [
        {
            "name": "문막(인천)",
            "lat": 37.31,
            "lon": 127.49,
            "route_name": "영동",
            "route_no": "50",
            "direction": "상행",
            "direction_raw": "인천"    <- 괄호에서 추출한 도시명
        },
        ...
    ]

참고:
    - xValue = 경도(longitude), yValue = 위도(latitude) (WGS84 decimal degrees)
    - unitName 에 '(인천)', '(상행)', '(하행)' 등 방향 정보가 포함되어 있습니다.
    - 좌표가 0 이거나 비정상인 항목은 자동 제외됩니다.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from scripts._direction_utils import parse_name_direction

BASE_URL = "https://data.ex.co.kr/openapi/locationinfo/locationinfoRest"


def fetch_all(api_key: str, rows_per_page: int = 1000) -> list[dict]:
    """API를 paginate하며 전체 휴게소 목록을 반환합니다."""
    all_items: list[dict] = []
    page = 1

    with httpx.Client(timeout=30) as client:
        while True:
            params = {
                "key":        api_key,
                "type":       "json",
                "numOfRows":  rows_per_page,
                "pageNo":     page,
            }
            resp = client.get(BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            # 응답 구조: {"list": [...], "totalCount": N, "numOfRows": N, "pageNo": N}
            items = data.get("list", [])
            if not items:
                break

            all_items.extend(items)

            total = int(data.get("totalCount", 0) or data.get("count", 0))
            print(f"  페이지 {page}: {len(items)}건 수신 (누적 {len(all_items)}/{total})")

            if len(all_items) >= total:
                break
            page += 1
            time.sleep(0.3)   # API 레이트 리밋 대응

    return all_items


def parse_item(item: dict) -> dict | None:
    """API 응답 한 항목 → 캐시 레코드. 좌표 이상 시 None."""
    try:
        # xValue = 경도, yValue = 위도 (WGS84 decimal degrees)
        lon = float(item.get("xValue") or 0)
        lat = float(item.get("yValue") or 0)
    except (ValueError, TypeError):
        return None

    if lat == 0 or lon == 0 or not (33 < lat < 39) or not (124 < lon < 132):
        return None   # 좌표 범위 밖이면 제외

    name       = str(item.get("unitName", "")).strip()
    route_name = str(item.get("routeName", "")).strip()
    route_no   = str(item.get("routeNo", "")).strip()

    direction = parse_name_direction(name)

    # 괄호 안 도시명(방향 표시) 추출
    import re
    m = re.search(r"\(([^)]+)\)", name)
    direction_raw = m.group(1).strip() if m else ""

    return {
        "name":          name,
        "lat":           lat,
        "lon":           lon,
        "route_name":    route_name,
        "route_no":      route_no,
        "direction":     direction,
        "direction_raw": direction_raw,
    }


def run(api_key: str, out_path: Path, rows_per_page: int) -> None:
    print("한국도로공사 휴게소 API 호출 중...")
    raw_items = fetch_all(api_key, rows_per_page)
    print(f"API 응답 총 {len(raw_items)}건\n")

    results = []
    skipped = 0
    for item in raw_items:
        rec = parse_item(item)
        if rec is None:
            skipped += 1
        else:
            results.append(rec)

    results.sort(key=lambda x: x["name"])

    n_up   = sum(1 for r in results if r["direction"] == "상행")
    n_down = sum(1 for r in results if r["direction"] == "하행")
    n_none = sum(1 for r in results if r["direction"] is None)

    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"휴게소 {len(results)}개 저장 → {out_path}")
    print(f"  상행: {n_up}개 / 하행: {n_down}개 / 미분류: {n_none}개")
    if skipped:
        print(f"  좌표 이상 스킵: {skipped}개")


def main() -> None:
    parser = argparse.ArgumentParser(description="한국도로공사 휴게소 API → JSON 캐시")
    parser.add_argument("--key",  required=True, help="data.ex.co.kr API 인증키")
    parser.add_argument("--rows", type=int, default=1000, help="페이지당 건수 (기본 1000)")
    parser.add_argument(
        "--out",
        default=str(ROOT / "backend" / "ex_rest_stops_cache.json"),
        help="출력 파일 경로",
    )
    args = parser.parse_args()

    run(api_key=args.key, out_path=Path(args.out), rows_per_page=args.rows)


if __name__ == "__main__":
    main()

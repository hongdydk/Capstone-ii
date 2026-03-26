"""졸음쉼터 CSV → 방향(상행/하행) 포함 JSON 캐시 빌드

입력:  자료/한국도로공사_졸음쉼터_20260225.csv  (EUC-KR)
출력:  backend/drowsy_shelter_cache.json

실행:
    cd C:/CapstoneII
    .venv\\Scripts\\python.exe backend/scripts/build_drowsy_cache.py

출력 포맷:
    [
        {
            "name": "오창",
            "lat": 36.73464638,
            "lon": 127.4566151,
            "route_name": "중부선",
            "route_no": "35",
            "direction": "상행",       # "상행" / "하행" / null
            "direction_raw": "통영기점 + 하남종점"
        },
        ...
    ]
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from scripts._direction_utils import parse_route_direction

CSV_PATH = ROOT / "자료" / "한국도로공사_졸음쉼터_20260225.csv"
OUT_PATH = ROOT / "backend" / "drowsy_shelter_cache.json"

# CSV 컬럼 인덱스
COL_NAME      = 0   # 졸음쉼터명
COL_ROUTE_NM  = 4   # 도로노선명
COL_ROUTE_NO  = 5   # 도로노선번호
COL_DIRECTION = 6   # 도로노선방향 ('통영기점 + 하남종점')
COL_LAT       = 9   # 위도
COL_LON       = 10  # 경도


def build() -> None:
    results: list[dict] = []
    skipped = 0

    with open(CSV_PATH, encoding="euc-kr", newline="") as f:
        reader = csv.reader(f)
        next(reader)  # 헤더 건너뜀
        for row in reader:
            if len(row) <= COL_LON:
                continue
            try:
                lat = float(row[COL_LAT])
                lon = float(row[COL_LON])
            except ValueError:
                skipped += 1
                continue

            name          = row[COL_NAME].strip()
            route_name    = row[COL_ROUTE_NM].strip()
            route_no      = row[COL_ROUTE_NO].strip()
            direction_raw = row[COL_DIRECTION].strip()

            direction = parse_route_direction(direction_raw)

            results.append({
                "name":          name,
                "lat":           lat,
                "lon":           lon,
                "route_name":    route_name,
                "route_no":      route_no,
                "direction":     direction,        # "상행" / "하행" / null
                "direction_raw": direction_raw,
            })

    # 통계
    total   = len(results)
    n_up    = sum(1 for r in results if r["direction"] == "상행")
    n_down  = sum(1 for r in results if r["direction"] == "하행")
    n_none  = sum(1 for r in results if r["direction"] is None)

    OUT_PATH.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"졸음쉼터 {total}개 저장 → {OUT_PATH}")
    print(f"  상행: {n_up}개 / 하행: {n_down}개 / 미분류: {n_none}개")
    if skipped:
        print(f"  좌표 없음 스킵: {skipped}개")


if __name__ == "__main__":
    build()

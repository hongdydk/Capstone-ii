"""
고속도로 휴게소 + 졸음쉼터 시드 스크립트

실행:
    cd backend
    python seeds/seed_rest_stops.py

주의:
  - 스크립트 실행 전 .env 파일에 DATABASE_URL이 설정되어 있어야 합니다.
  - 고속도로 휴게소 시드를 위해 EX_API_KEY (한국도로공사 공공데이터 포털 인증키)가
    필요합니다. 없으면 졸음쉼터만 삽입합니다.
    발급: https://data.ex.co.kr
"""
import asyncio
import csv
import os
import sys
from pathlib import Path

# backend/ 기준으로 패키지 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DATABASE_URL: str = os.environ["DATABASE_URL"].replace(
    "postgresql+asyncpg://", "postgresql://"
)
EX_API_KEY: str = os.environ.get("EX_API_KEY", "")

# 졸음쉼터 CSV 경로 (프로젝트 루트 기준)
DROWSY_CSV: Path = Path(__file__).parent.parent.parent / "자료" / "한국도로공사_졸음쉼터_20260225.csv"

# 한국도로공사 휴게소 위치정보 OpenAPI
_EX_REST_URL = "https://data.ex.co.kr/openapi/locationinfo/locationinfoRest"
_EX_PAGE_SIZE = 100


async def _fetch_highway_rests() -> list[dict]:
    """한국도로공사 OpenAPI로 고속도로 휴게소 전체 목록을 페이지 순회하며 조회합니다.
    반환값: [{"name": str, "lat": float, "lon": float, "route_name": str | None}, ...]

    좌표계: API xValue=경도(WGS84), yValue=위도(WGS84)
    """
    results: list[dict] = []
    page = 1

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            resp = await client.get(
                _EX_REST_URL,
                params={
                    "key": EX_API_KEY,
                    "type": "json",
                    "numOfRows": str(_EX_PAGE_SIZE),
                    "pageNo": str(page),
                },
            )
            resp.raise_for_status()
            data = resp.json()

            items = data.get("list", [])
            if not items:
                break

            for item in items:
                try:
                    lon = float(item.get("xValue") or 0)
                    lat = float(item.get("yValue") or 0)
                    if lat == 0 or lon == 0:
                        continue
                    results.append({
                        "name": item.get("unitName") or "휴게소",
                        "lat": lat,
                        "lon": lon,
                        "route_name": item.get("routeName") or None,
                    })
                except (ValueError, TypeError):
                    continue

            # 마지막 페이지 판단
            try:
                total_pages = int(data.get("pageSize") or 1)
            except (ValueError, TypeError):
                total_pages = 1

            if page >= total_pages or len(items) < _EX_PAGE_SIZE:
                break
            page += 1

    return results


async def seed() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # ── 졸음쉼터 (한국도로공사 공공 데이터 CSV) ──────────────────────────
        drowsy_inserted = 0
        if DROWSY_CSV.exists():
            with open(DROWSY_CSV, encoding="euc-kr", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        lat = float(row.get("위도") or 0)
                        lon = float(row.get("경도") or 0)
                        name = row.get("졸음쉼터명") or "졸음쉼터"
                        direction = row.get("도로노선방향") or None
                        if lat == 0 or lon == 0:
                            continue
                        await conn.execute(
                            """
                            INSERT INTO rest_stops (name, type, latitude, longitude, direction, is_active, scope)
                            VALUES ($1, 'drowsy_shelter', $2, $3, $4, true, 'public')
                            ON CONFLICT DO NOTHING
                            """,
                            name, lat, lon, direction,
                        )
                        drowsy_inserted += 1
                    except (ValueError, KeyError):
                        continue
            print(f"졸음쉼터 {drowsy_inserted}건 삽입 완료")
        else:
            print(f"CSV 파일 없음 (졸음쉼터 건너뜀): {DROWSY_CSV}")

        # ── 고속도로 휴게소 (한국도로공사 OpenAPI) ────────────────────────────
        if not EX_API_KEY:
            raise EnvironmentError(
                "EX_API_KEY가 설정되지 않았습니다. "
                "backend/.env 에 EX_API_KEY=<인증키> 를 추가하세요. "
                "발급: https://data.ex.co.kr"
            )
        else:
            print("고속도로 휴게소 조회 중...")
            highway_rests = await _fetch_highway_rests()
            highway_inserted = 0
            for item in highway_rests:
                await conn.execute(
                    """
                    INSERT INTO rest_stops (name, type, latitude, longitude, is_active, scope, note)
                    VALUES ($1, 'highway_rest', $2, $3, true, 'public', $4)
                    ON CONFLICT DO NOTHING
                    """,
                    item["name"], item["lat"], item["lon"], item["route_name"],
                )
                highway_inserted += 1
            print(f"고속도로 휴게소 {highway_inserted}건 삽입 완료")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())

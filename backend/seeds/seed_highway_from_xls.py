"""
XLS 파일(국가물류통합정보센터 화물차 전용 휴게소) 기준으로 highway_rest 재시드.

처리 순서:
  1. XLS에서 운영중 휴게소 목록 추출
  2. 한국도로공사 OpenAPI 전 페이지 조회 → 이름 매칭으로 좌표 획득
  3. API 미매칭 항목은 Kakao 로컬 검색으로 좌표 보완
  4. 기존 highway_rest 전체 삭제 후 재삽입

실행:
    cd backend
    python seeds/seed_highway_from_xls.py
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
import httpx
import xlrd
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent.parent / ".env")

DATABASE_URL: str = os.environ["DATABASE_URL"].replace(
    "postgresql+asyncpg://", "postgresql://"
)
EX_API_KEY: str = os.environ.get("EX_API_KEY", "")
KAKAO_API_KEY: str = os.environ.get("KAKAO_API_KEY", "")

XLS_PATH = Path(__file__).parent.parent.parent / "자료" / "휴게소정보_260325.xls"

_EX_REST_URL = "https://data.ex.co.kr/openapi/locationinfo/locationinfoRest"
_KAKAO_LOCAL_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


def normalize(s: str) -> str:
    """비교용 정규화: 공백 제거, 소문자, '휴게소'/'쉼터' 제거."""
    return re.sub(r"\s+", "", s).replace("휴게소", "").replace("쉼터", "").lower()


def load_xls_names() -> list[dict]:
    """XLS에서 운영중 휴게소 추출. 반환: [{"name": str, "route": str}, ...]"""
    wb = xlrd.open_workbook(str(XLS_PATH))
    ws = wb.sheet_by_index(0)
    result = []
    for r in range(1, ws.nrows):
        status = str(ws.cell_value(r, 1)).strip()
        name = str(ws.cell_value(r, 3)).strip()
        route = str(ws.cell_value(r, 4)).strip()
        if name and status == "운영중":
            result.append({"name": name, "route": route})
    return result


async def fetch_ex_api_all() -> list[dict]:
    """EX API 전 페이지 조회. 반환: [{"name": str, "lat": float, "lon": float}, ...]"""
    results = []
    page = 1
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            resp = await client.get(
                _EX_REST_URL,
                params={
                    "key": EX_API_KEY,
                    "type": "json",
                    "numOfRows": "100",
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
                        "name": item.get("unitName") or "",
                        "lat": lat,
                        "lon": lon,
                    })
                except (ValueError, TypeError):
                    continue
            try:
                total_pages = int(data.get("pageSize") or 1)
            except (ValueError, TypeError):
                total_pages = 1
            print(f"  EX API page {page}/{total_pages} → {len(items)}건")
            if page >= total_pages or len(items) < 100:
                break
            page += 1
    return results


async def kakao_geocode(name: str, route: str, client: httpx.AsyncClient) -> dict | None:
    """Kakao 로컬 검색으로 좌표 획득. 반환: {"lat": float, "lon": float} or None"""
    query = f"{name}휴게소 {route}선"
    try:
        resp = await client.get(
            _KAKAO_LOCAL_URL,
            headers={"Authorization": f"KakaoAK {KAKAO_API_KEY}"},
            params={"query": query, "size": 1},
        )
        if resp.status_code != 200:
            return None
        docs = resp.json().get("documents", [])
        if not docs:
            # 재시도: 노선 없이
            resp2 = await client.get(
                _KAKAO_LOCAL_URL,
                headers={"Authorization": f"KakaoAK {KAKAO_API_KEY}"},
                params={"query": f"{name}휴게소", "size": 1},
            )
            if resp2.status_code != 200:
                return None
            docs = resp2.json().get("documents", [])
        if not docs:
            return None
        return {"lat": float(docs[0]["y"]), "lon": float(docs[0]["x"])}
    except Exception:
        return None


async def main():
    if not EX_API_KEY:
        print("EX_API_KEY 없음 — .env 확인")
        return
    if not KAKAO_API_KEY:
        print("KAKAO_API_KEY 없음 — .env 확인")
        return

    # 1. XLS 목록
    xls_list = load_xls_names()
    print(f"XLS 운영중 휴게소: {len(xls_list)}개")

    # 2. EX API 전체 조회
    print("EX API 조회 중...")
    ex_list = await fetch_ex_api_all()
    print(f"EX API 총 {len(ex_list)}건 수신")

    # 이름→좌표 맵 (정규화 키)
    ex_map: dict[str, dict] = {normalize(r["name"]): r for r in ex_list}

    # 3. XLS 각 항목에 좌표 매핑
    matched, unmatched = 0, 0
    to_insert: list[dict] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for item in xls_list:
            key = normalize(item["name"])
            if key in ex_map:
                to_insert.append({
                    "name": item["name"] + "휴게소",
                    "lat": ex_map[key]["lat"],
                    "lon": ex_map[key]["lon"],
                    "note": item["route"],
                })
                matched += 1
            else:
                # Kakao 지오코딩 시도
                coord = await kakao_geocode(item["name"], item["route"], client)
                if coord:
                    to_insert.append({
                        "name": item["name"] + "휴게소",
                        "lat": coord["lat"],
                        "lon": coord["lon"],
                        "note": item["route"],
                    })
                    print(f"  [Kakao] {item['name']} → {coord['lat']:.5f}, {coord['lon']:.5f}")
                    matched += 1
                else:
                    print(f"  [미매칭] {item['name']} (노선: {item['route']})")
                    unmatched += 1

    print(f"\n좌표 확보: {matched}개 / 미확보: {unmatched}개")

    # 4. DB 재삽입
    conn = await asyncpg.connect(DATABASE_URL, ssl=False)
    try:
        await conn.execute("DELETE FROM rest_stops WHERE type = 'highway_rest'")
        print("기존 highway_rest 삭제 완료")

        inserted = 0
        for item in to_insert:
            await conn.execute(
                """
                INSERT INTO rest_stops (name, type, latitude, longitude, is_active, scope, note)
                VALUES ($1, 'truck_rest', $2, $3, true, 'public', $4)
                ON CONFLICT DO NOTHING
                """,
                item["name"], item["lat"], item["lon"], item["note"],
            )
            inserted += 1
        print(f"highway_rest {inserted}건 삽입 완료")

        # 최종 현황
        total = await conn.fetchval("SELECT COUNT(*) FROM rest_stops")
        hw = await conn.fetchval("SELECT COUNT(*) FROM rest_stops WHERE type = 'highway_rest'")
        dr = await conn.fetchval("SELECT COUNT(*) FROM rest_stops WHERE type = 'drowsy_shelter'")
        print(f"\n최종 DB 현황: highway_rest={hw}, drowsy_shelter={dr}, 합계={total}")
    finally:
        await conn.close()


asyncio.run(main())

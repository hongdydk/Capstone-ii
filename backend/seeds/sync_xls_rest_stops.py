"""
XLS 휴게소 데이터 → DB 좌표 검증 및 동기화

실행:
    cd backend
    python seeds/sync_xls_rest_stops.py

처리 순서:
  1. XLS 파일에서 휴게소명 + 주소 읽기
  2. Kakao 주소 지오코딩 API로 좌표 획득
  3. DB truck_rest와 이름 매칭:
     - 매칭 O + 좌표 차이 > 0.003° (~300m): UPDATE
     - 매칭 X: INSERT
  4. DB에만 있고 XLS에 없는 항목 리포트 (삭제 여부는 수동 판단)
"""
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
import httpx
import xlrd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DATABASE_URL: str = os.environ["DATABASE_URL"].replace(
    "postgresql+asyncpg://", "postgresql://"
)
KAKAO_API_KEY: str = os.environ.get("KAKAO_API_KEY", "")
XLS_PATH: Path = Path(__file__).parent.parent.parent / "자료" / "휴게소정보_260325.xls"

COORD_DIFF_THRESHOLD = 0.003  # 약 300m 이상 차이면 업데이트


def load_xls() -> list[dict]:
    """XLS에서 [{'raw_name': str, 'full_name': str, 'address': str}] 반환."""
    wb = xlrd.open_workbook(str(XLS_PATH), encoding_override="cp949")
    sh = wb.sheet_by_index(0)
    results = []
    for r in range(1, sh.nrows):
        row = [sh.cell_value(r, c) for c in range(sh.ncols)]
        raw_name = str(row[3]).strip()
        address = str(row[5]).strip()
        if not raw_name or not address:
            continue
        # DB 이름 규칙: 괄호 있으면 그대로 + '휴게소', 없으면 + '휴게소'
        # 예: '문막(인천)' → '문막(인천)휴게소', '부산신항' → '부산신항휴게소'
        if raw_name.endswith("휴게소"):
            full_name = raw_name
        else:
            full_name = raw_name + "휴게소"
        results.append({"raw_name": raw_name, "full_name": full_name, "address": address})
    return results


async def kakao_geocode(address: str, client: httpx.AsyncClient) -> tuple[float, float] | None:
    """Kakao 주소 검색 API로 (lat, lon) 반환. 실패 시 None."""
    try:
        resp = await client.get(
            "https://dapi.kakao.com/v2/local/search/address.json",
            params={"query": address, "size": 1},
            headers={"Authorization": f"KakaoAK {KAKAO_API_KEY}"},
            timeout=10,
        )
        resp.raise_for_status()
        docs = resp.json().get("documents", [])
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])  # lat, lon
    except Exception as e:
        print(f"  [지오코딩 실패] {address}: {e}")
    return None


def name_key(name: str) -> str:
    """비교용 정규화: 공백/특수문자 제거, 소문자."""
    return re.sub(r"[\s\(\)\-·]", "", name).lower()


async def main():
    if not KAKAO_API_KEY:
        print("ERROR: KAKAO_API_KEY 미설정")
        sys.exit(1)

    xls_entries = load_xls()
    print(f"XLS 로드: {len(xls_entries)}건\n")

    conn = await asyncpg.connect(DATABASE_URL)
    db_rows = await conn.fetch(
        "SELECT id, name, latitude, longitude FROM rest_stops WHERE type='truck_rest'"
    )
    db_map: dict[str, dict] = {
        name_key(r["name"]): {"id": r["id"], "name": r["name"], "lat": float(r["latitude"]), "lon": float(r["longitude"])}
        for r in db_rows
    }

    updates: list[dict] = []
    inserts: list[dict] = []

    async with httpx.AsyncClient() as client:
        for entry in xls_entries:
            key = name_key(entry["full_name"])
            coords = await kakao_geocode(entry["address"], client)

            if coords is None:
                print(f"  ⚠ 지오코딩 실패: {entry['full_name']} ({entry['address']})")
                continue

            new_lat, new_lon = coords

            if key in db_map:
                db = db_map[key]
                diff = abs(db["lat"] - new_lat) + abs(db["lon"] - new_lon)
                if diff > COORD_DIFF_THRESHOLD:
                    updates.append({
                        "id": db["id"],
                        "name": db["name"],
                        "old_lat": db["lat"], "old_lon": db["lon"],
                        "new_lat": new_lat, "new_lon": new_lon,
                        "diff": diff,
                        "address": entry["address"],
                    })
                    print(f"  📍 좌표 불일치: {db['name']}")
                    print(f"     현재: ({db['lat']:.5f}, {db['lon']:.5f})")
                    print(f"     Kakao: ({new_lat:.5f}, {new_lon:.5f})  diff={diff:.5f}")
                else:
                    print(f"  ✓ 정상: {entry['full_name']} ({new_lat:.5f}, {new_lon:.5f})")
            else:
                inserts.append({
                    "full_name": entry["full_name"],
                    "new_lat": new_lat, "new_lon": new_lon,
                    "address": entry["address"],
                })
                print(f"  ➕ 신규: {entry['full_name']} ({new_lat:.5f}, {new_lon:.5f})")

    # DB에만 있고 XLS에 없는 항목
    xls_keys = {name_key(e["full_name"]) for e in xls_entries}
    only_in_db = [v for k, v in db_map.items() if k not in xls_keys]

    print(f"\n{'='*60}")
    print(f"결과 요약")
    print(f"{'='*60}")
    print(f"  좌표 업데이트 필요: {len(updates)}건")
    print(f"  신규 추가 필요:     {len(inserts)}건")
    print(f"  DB에만 있는 항목:   {len(only_in_db)}건")

    if only_in_db:
        print("\n[DB에만 있음 — XLS에서 제외된 항목]")
        for r in only_in_db:
            print(f"  id={r['id']}  {r['name']}")

    if not (updates or inserts):
        print("\n변경사항 없음.")
        await conn.close()
        return

    answer = input(f"\n위 {len(updates)}건 업데이트 + {len(inserts)}건 삽입 진행? (y/n): ").strip().lower()
    if answer != "y":
        print("취소됨.")
        await conn.close()
        return

    # UPDATE
    for u in updates:
        await conn.execute(
            "UPDATE rest_stops SET latitude=$1, longitude=$2 WHERE id=$3",
            u["new_lat"], u["new_lon"], u["id"],
        )
        print(f"  [UPDATE] {u['name']} → ({u['new_lat']:.5f}, {u['new_lon']:.5f})")

    # INSERT
    for ins in inserts:
        await conn.execute(
            """INSERT INTO rest_stops (name, latitude, longitude, type, direction, is_active, scope)
               VALUES ($1, $2, $3, 'truck_rest', NULL, TRUE, 'public')
               ON CONFLICT DO NOTHING""",
            ins["full_name"], ins["new_lat"], ins["new_lon"],
        )
        print(f"  [INSERT] {ins['full_name']} ({ins['new_lat']:.5f}, {ins['new_lon']:.5f})")

    print(f"\n완료: {len(updates)}건 업데이트, {len(inserts)}건 삽입")
    await conn.close()


asyncio.run(main())

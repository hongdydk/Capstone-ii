"""실제 물류 데이터 VRP 검증 데모

물류단지정보_260325.xls + 물류창고정보_260325.xls 에서 무작위로
  - 단지 1곳 (출발지)
  - 창고 N곳 (경유지, 기본 4곳)
  - 창고 1곳 (도착지)
를 선택하여 TMAP 지오코딩 → 시간 행렬 → OR-Tools TSP → 법정 휴게 삽입 순서로
실제 데이터 기반 VRP 최적화를 검증합니다.

사용법:
    cd C:/CapstoneII
    .venv\\Scripts\\python.exe backend/demo_real_data.py
    .venv\\Scripts\\python.exe backend/demo_real_data.py --waypoints 6 --seed 42
"""

import argparse
import asyncio
import logging
import random
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env", override=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
import xlrd

from app.core.config import settings
from app.services.route_optimizer import (
    MAX_DRIVE_SEC,
    MIN_REST_SEC,
    REST_PLAN_SEC,
    build_matrices,
    haversine_m,
    haversine_sec,
    insert_rest_stops,
    solve_tsp,
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

ROOT      = Path(__file__).resolve().parents[1]
XLS_DEPOT = ROOT / "자료" / "물류단지정보_260325.xls"
XLS_WH    = ROOT / "자료" / "물류창고정보_260325.xls"
GEOCODE_URL = "https://apis.openapi.sk.com/tmap/geo/fullAddrGeo"

TRUCK = {"height": 4.0, "weight": 25000, "length": 1600, "width": 250}


# ── 지오코딩 ─────────────────────────────────────────────────────────────────

async def geocode(address: str, sem: asyncio.Semaphore) -> tuple[float, float] | None:
    async with sem:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    GEOCODE_URL,
                    params={"version": "1", "fullAddr": address,
                            "appKey": settings.TMAP_APP_KEY},
                )
                resp.raise_for_status()
                coords = resp.json().get("coordinateInfo", {}).get("coordinate", [])
                if coords:
                    lat = float(coords[0].get("newLat") or coords[0].get("lat") or 0)
                    lon = float(coords[0].get("newLon") or coords[0].get("lon") or 0)
                    if lat and lon:
                        return lat, lon
        except Exception:
            pass
    return None


# ── XLS 파싱 ─────────────────────────────────────────────────────────────────

def load_depots() -> list[dict]:
    """물류단지 목록 (운영중 한정)."""
    wb = xlrd.open_workbook(str(XLS_DEPOT))
    ws = wb.sheet_by_index(0)
    rows = []
    for r in range(1, ws.nrows):
        name    = str(ws.cell_value(r, 0)).strip()
        address = str(ws.cell_value(r, 2)).strip()
        status  = str(ws.cell_value(r, 14)).strip()
        if name and address and "운영" in status:
            rows.append({"name": name, "address": address})
    return rows


def load_warehouses() -> list[dict]:
    """물류창고 목록."""
    wb = xlrd.open_workbook(str(XLS_WH))
    ws = wb.sheet_by_index(0)
    rows = []
    for r in range(1, ws.nrows):
        name    = str(ws.cell_value(r, 0)).strip()
        address = str(ws.cell_value(r, 2)).strip()
        if name and address:
            rows.append({"name": name, "address": address})
    return rows


# ── 도우미 ────────────────────────────────────────────────────────────────────

def fmt_time(seconds: int) -> str:
    h, m = divmod(abs(seconds) // 60, 60)
    return f"{h}시간 {m:02d}분" if h else f"{m}분"


# ── 메인 ─────────────────────────────────────────────────────────────────────

async def run(n_waypoints: int, seed: int | None) -> None:
    rng = random.Random(seed)

    # 1. XLS 로드
    depots = load_depots()
    warehouses = load_warehouses()
    print(f"물류단지 운영중: {len(depots)}곳  /  물류창고: {len(warehouses)}곳\n")

    # 2. 무작위 선택 (단지 1 + 창고 n+1)
    origin_meta = rng.choice(depots)
    picks = rng.sample(warehouses, n_waypoints + 1)
    waypoint_metas = picks[:n_waypoints]
    dest_meta      = picks[n_waypoints]

    print("=" * 65)
    print("  무작위 선택 결과")
    print("=" * 65)
    print(f"  [출발] {origin_meta['name']}")
    print(f"         {origin_meta['address']}")
    for i, w in enumerate(waypoint_metas, 1):
        print(f"  [경유{i}] {w['name']}")
        print(f"         {w['address']}")
    print(f"  [도착] {dest_meta['name']}")
    print(f"         {dest_meta['address']}")
    print()

    # 3. 지오코딩
    print("[1] TMAP 지오코딩 중...")
    sem = asyncio.Semaphore(4)
    all_metas = [origin_meta, *waypoint_metas, dest_meta]
    tasks = [geocode(m["address"], sem) for m in all_metas]
    coords = await asyncio.gather(*tasks)

    nodes = []
    failed = []
    roles  = ["origin"] + ["waypoint"] * n_waypoints + ["destination"]
    for meta, coord, role in zip(all_metas, coords, roles):
        if coord:
            nodes.append({"name": meta["name"], "lat": coord[0], "lon": coord[1], "type": role})
        else:
            failed.append(meta["name"])

    if failed:
        print(f"  ⚠ 지오코딩 실패 → 제외: {', '.join(failed)}")

    if len(nodes) < 2:
        print("  노드 부족으로 중단.")
        return

    print(f"  지오코딩 성공: {len(nodes)}개 노드\n")
    for nd in nodes:
        print(f"    {'['+nd['type']+']':<16} {nd['name'][:30]:<32} ({nd['lat']:.4f}, {nd['lon']:.4f})")
    print()

    # 4. DB에서 휴게소 로드 (docker 없으면 하드코딩 fallback)
    rest_stops = await _load_rest_stops_from_db()

    # 5. 시간 행렬 (TMAP 화물차 API)
    n = len(nodes)
    print(f"[2] TMAP 화물차 경로 API 시간 행렬 구성... ({n}×{n-1}={n*(n-1)}회 호출)")
    matrix, _ = await build_matrices(
        nodes,
        vehicle_height=TRUCK["height"],
        vehicle_weight=TRUCK["weight"],
        vehicle_length=TRUCK["length"],
        vehicle_width=TRUCK["width"],
    )

    # 시간 행렬 출력
    col_w = 12
    header = " " * 20 + "".join(nd["name"][:col_w-2].center(col_w) for nd in nodes)
    print(f"\n  소요 시간 행렬 (TMAP 화물차):")
    print("  " + header)
    for i, row in enumerate(matrix):
        cells = "".join(fmt_time(v).center(col_w) for v in row)
        print(f"  {nodes[i]['name'][:18]:<18}  {cells}")
    print()

    # 6. TSP 최적화
    print("[3] OR-Tools TSP 최적화")
    start_idx = 0
    end_idx   = len(nodes) - 1

    if len(nodes) <= 2:
        tsp_order = [0, 1]
    else:
        tsp_order = solve_tsp(matrix, start=start_idx, end=end_idx)

    ordered = [nodes[i] for i in tsp_order]
    print(f"  입력 순서: {' → '.join(nd['name'][:8] for nd in nodes)}")
    print(f"  최적 순서: {' → '.join(nd['name'][:8] for nd in ordered)}")

    # 순서 바뀐 경유지 강조
    input_wps = [nd["name"] for nd in nodes[1:-1]]
    opt_wps   = [nd["name"] for nd in ordered[1:-1]]
    if input_wps != opt_wps:
        print(f"  ★ 경유지 순서 변경됨!")
    else:
        print(f"  (경유지 순서 변경 없음)")

    raw_time = sum(matrix[tsp_order[i]][tsp_order[i+1]] for i in range(len(tsp_order)-1))
    print(f"  순수 이동 시간: {fmt_time(raw_time)}")
    print()

    # 7. 법정 휴게 삽입 (우회 비용 최소화)
    print(f"[4] 법정 휴게 삽입 (계획 임계: {fmt_time(REST_PLAN_SEC)}, 법정 한도: {fmt_time(MAX_DRIVE_SEC)})")
    final = insert_rest_stops(ordered, matrix, tsp_order, rest_stops)

    print(f"\n  최종 경로 (휴게소 {sum(1 for nd in final if nd.get('type')=='rest_stop')}개 삽입):")
    print("  " + "-" * 62)
    cumul_sec = 0
    prev_node = None
    for i, node in enumerate(final):
        t = node.get("type", "?")
        if t == "rest_stop":
            print(f"  {i+1:2d}. [휴게소       ] {'☕ '+node['name']:<32} (휴식 {node.get('min_rest_minutes',15)}분)")
            cumul_sec += MIN_REST_SEC
        else:
            if prev_node:
                seg = haversine_sec(prev_node["lat"], prev_node["lon"], node["lat"], node["lon"])
                dist_km = haversine_m(prev_node["lat"], prev_node["lon"], node["lat"], node["lon"]) / 1000
                cumul_sec += seg
                suffix = f"(+{fmt_time(seg)}, {dist_km:.0f}km)"
            else:
                suffix = "(출발)"
            print(f"  {i+1:2d}. [{t:<12}] {node['name'][:32]:<32} {suffix}")
        if t != "rest_stop":
            prev_node = node

    print("  " + "-" * 62)
    rest_count = sum(1 for nd in final if nd.get("type") == "rest_stop")
    print(f"  삽입된 휴게소: {rest_count}개")
    print(f"  총 예상 소요:  {fmt_time(cumul_sec)} (이동 + 의무 휴게)")
    print()

    # 8. 입력 순서 vs 최적 순서 비교
    if len(nodes) > 3:
        print("[5] 입력 순서 vs 최적 순서 비교")
        naive_time = sum(matrix[i][i+1] for i in range(len(nodes)-1))
        saving = naive_time - raw_time
        sign = "절감" if saving >= 0 else "증가"
        print(f"  입력 순서 이동 시간: {fmt_time(naive_time)}")
        print(f"  최적 순서 이동 시간: {fmt_time(raw_time)}")
        print(f"  시간 {sign}: {fmt_time(abs(saving))}")
        if naive_time > 0:
            pct = abs(saving) / naive_time * 100
            print(f"  효율 {'향상' if saving>=0 else '저하'}: {pct:.1f}%")
    print()


async def _load_rest_stops_from_db() -> list[dict]:
    """Docker DB가 살아있으면 실제 DB에서, 아니면 주요 휴게소 하드코딩으로 fallback."""
    try:
        import subprocess, json
        result = subprocess.run(
            ["docker", "exec", "routeon-db", "psql", "-U", "routeon", "-d", "routeon",
             "-t", "-c",
             "SELECT name, latitude, longitude FROM rest_stops WHERE is_active LIMIT 100;"],
            capture_output=True, timeout=5,
        )
        if result.returncode == 0:
            rows = []
            for line in result.stdout.decode("utf-8").splitlines():
                parts = [p.strip() for p in line.split("|")]
                if len(parts) == 3 and parts[0]:
                    try:
                        rows.append({"name": parts[0], "lat": float(parts[1]), "lon": float(parts[2])})
                    except ValueError:
                        pass
            if rows:
                print(f"  DB 휴게소 로드: {len(rows)}건\n")
                return rows
    except Exception:
        pass

    # fallback: 고속도로 주요 휴게소
    fallback = [
        {"name": "안성휴게소",   "lat": 37.0107, "lon": 127.2699},
        {"name": "천안논산휴게소","lat": 36.5760, "lon": 127.1461},
        {"name": "공주휴게소",   "lat": 36.4389, "lon": 127.1270},
        {"name": "논산천안휴게소","lat": 36.2280, "lon": 127.1119},
        {"name": "익산휴게소",   "lat": 35.9449, "lon": 126.9686},
        {"name": "전주휴게소",   "lat": 35.7988, "lon": 127.1086},
        {"name": "고창담양휴게소","lat": 35.4364, "lon": 126.7024},
        {"name": "옥산휴게소",   "lat": 36.7079, "lon": 127.4272},
        {"name": "구미휴게소",   "lat": 36.1191, "lon": 128.3444},
        {"name": "칠원휴게소",   "lat": 35.2854, "lon": 128.4825},
        {"name": "언양휴게소",   "lat": 35.5563, "lon": 129.0866},
        {"name": "양산휴게소",   "lat": 35.3415, "lon": 129.0135},
        {"name": "북창원휴게소", "lat": 35.2635, "lon": 128.6467},
        {"name": "신탄진휴게소", "lat": 36.4660, "lon": 127.4078},
        {"name": "오산휴게소",   "lat": 37.1527, "lon": 127.0759},
    ]
    print(f"  DB 미연결 → 하드코딩 휴게소 {len(fallback)}건 사용\n")
    return fallback


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="실제 물류 데이터 VRP 검증")
    parser.add_argument("--waypoints", type=int, default=4,  help="경유 창고 수 (기본 4)")
    parser.add_argument("--seed",      type=int, default=None, help="랜덤 시드 (재현용)")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(run(args.waypoints, args.seed))

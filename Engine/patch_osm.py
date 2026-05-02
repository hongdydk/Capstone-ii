"""
OSM PBF + MOCT 속성 패치 파이프라인
====================================
국가표준노드링크(MOCT_LINK.shp)의 속성을 OSM PBF의 highway way 태그에 반영합니다.

패치 항목
---------
- MAX_SPD  → maxspeed (OSM에 없는 경우만 덮어쓰기)
- REST_VEH ∈ {4,5,6} → hgv=no  (화물차/대형차/위험물 통행제한)
- REST_H   > 0       → maxheight (MOCT 단위: cm → m 변환)
- REST_W   > 0       → maxweight (MOCT 단위: 0.1t, 예: 430 → 43.0t)

사용법
------
  python patch_osm.py [--moct-dir DIR] [--input INPUT.pbf] [--output OUTPUT.pbf]
  python patch_osm.py --dry-run   # 실제 PBF 쓰지 않고 매칭 통계만 출력

의존성
------
  pip install geopandas osmium shapely
"""

import argparse
import sys
from pathlib import Path
import time

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString
from shapely.strtree import STRtree
import osmium

# ── 기본 경로 ─────────────────────────────────────────────────────────────
BASE     = Path(__file__).parent
MOCT_SHP = BASE / "[2026-01-13]NODELINKDATA/MOCT_LINK.shp"
OSM_IN   = BASE / "south-korea-260501.osm.pbf"
OSM_OUT  = BASE / "south-korea-patched.osm.pbf"

# ── 매칭 파라미터 ─────────────────────────────────────────────────────────
# WGS84 기준 15m ≈ 0.000135°. 약간 여유를 둬 0.00018° (≈ 20m) 사용
BUFFER_DEG     = 0.00018
ANGLE_TOL_DEG  = 35      # 방향각 허용 오차 (도)

# REST_VEH 화물차 해당 코드 (4=대형차, 5=화물차, 6=위험물차량)
HGV_CODES = {4, 5, 6}

# MOCT 제한속도 0 = 제한없음 (무시)
# MOCT REST_H 단위: cm  (450 → 4.5m)
# MOCT REST_W 단위: 0.1t (430 → 43.0t = DB-24 기준)


def bearing(line: LineString) -> float:
    """라인의 시종점 방향각 반환 (0°~180°, 무방향성)."""
    coords = list(line.coords)
    dx = coords[-1][0] - coords[0][0]
    dy = coords[-1][1] - coords[0][1]
    return np.degrees(np.arctan2(dy, dx)) % 180


def angle_diff(a: float, b: float) -> float:
    """두 방향각의 최소 차이 (0°~90°)."""
    d = abs(a - b) % 180
    return min(d, 180 - d)


# ── Step 1: MOCT 링크 로드 ────────────────────────────────────────────────

def load_moct(shp_path: Path) -> tuple[list, list]:
    """
    MOCT_LINK.shp 로드 → WGS84 변환 → 패치 대상만 필터링.
    반환: (geometry 리스트, 속성 dict 리스트)
    """
    print(f"[1/4] MOCT 링크 로드: {shp_path}")
    gdf = gpd.read_file(str(shp_path), encoding="cp949")
    print(f"      CRS: {gdf.crs.to_epsg() or gdf.crs.name}")
    gdf = gdf.to_crs("EPSG:4326")

    # 패치할 값이 있는 링크만 추출
    mask = (
        (gdf["MAX_SPD"] > 0)
        | gdf["REST_VEH"].isin(HGV_CODES)
        | (gdf["REST_H"] > 0)
        | (gdf["REST_W"] > 0)
    )
    moct = gdf[mask].reset_index(drop=True)
    print(f"      패치 대상: {len(moct):,} / {len(gdf):,} 링크")

    geoms = list(moct.geometry)
    attrs = moct[["MAX_SPD", "REST_VEH", "REST_H", "REST_W"]].to_dict("records")
    return geoms, attrs


# ── Step 2: OSM way 매칭 → patches 수집 ─────────────────────────────────

class MatchHandler(osmium.SimpleHandler):
    """OSM PBF를 읽으며 MOCT 링크와 매칭, 패치 목록을 수집한다."""

    def __init__(self, moct_geoms: list, moct_attrs: list):
        super().__init__()
        self.tree  = STRtree(moct_geoms)
        self.geoms = moct_geoms
        self.attrs = moct_attrs
        self.patches: dict[int, dict] = {}   # {osm_way_id: {tag: value}}
        self._count = 0
        self._matched = 0

    def way(self, w):
        # 도로 태그가 없으면 스킵
        if "highway" not in w.tags:
            return

        # 노드 좌표 수집
        try:
            coords = [(n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        if len(coords) < 2:
            return

        self._count += 1
        line = LineString(coords)
        buf  = line.buffer(BUFFER_DEG)

        # 공간 인덱스로 후보 링크 탐색
        candidates = self.tree.query(buf, predicate="intersects")
        if len(candidates) == 0:
            return

        osm_angle  = bearing(line)
        best_score = -1.0
        best_attr  = None

        for idx in candidates:
            m_geom = self.geoms[idx]
            # 방향각 필터
            if angle_diff(osm_angle, bearing(m_geom)) > ANGLE_TOL_DEG:
                continue
            # 겹침 비율 점수 (MOCT 링크가 OSM 버퍼 안에 얼마나 포함되는지)
            try:
                overlap = buf.intersection(m_geom).length
            except Exception:
                continue
            score = overlap / max(m_geom.length, 1e-10)
            if score > best_score:
                best_score = score
                best_attr  = self.attrs[idx]

        # 겹침이 20% 미만이면 신뢰도 낮은 매칭으로 스킵
        if best_attr is None or best_score < 0.20:
            return

        patch: dict = {}
        existing = dict(w.tags)

        # 제한속도 (OSM에 이미 있으면 덮어쓰지 않음)
        spd = int(best_attr["MAX_SPD"])
        if spd > 0 and "maxspeed" not in existing:
            patch["maxspeed"] = str(spd)

        # 화물차 통행제한
        rest_veh = int(best_attr["REST_VEH"])
        if rest_veh in HGV_CODES:
            patch["hgv"] = "no"

        # 높이제한 (cm → m)
        rest_h = float(best_attr["REST_H"])
        if rest_h > 0 and "maxheight" not in existing:
            patch["maxheight"] = f"{rest_h / 100:.1f}"

        # 중량제한 (0.1t → t)
        rest_w = float(best_attr["REST_W"])
        if rest_w > 0 and "maxweight" not in existing:
            patch["maxweight"] = f"{rest_w / 10:.1f}"

        if patch:
            self.patches[w.id] = patch
            self._matched += 1

    def stats(self) -> None:
        print(f"      처리한 highway way: {self._count:,}")
        print(f"      패치 적용 way:      {self._matched:,}")


# ── Step 3: 패치된 PBF 출력 ───────────────────────────────────────────────

class WriteHandler(osmium.SimpleHandler):
    """patches 적용하며 새 PBF에 쓴다."""

    def __init__(self, writer: osmium.SimpleWriter, patches: dict):
        super().__init__()
        self.writer  = writer
        self.patches = patches

    def node(self, n):
        self.writer.add_node(n)

    def way(self, w):
        if w.id in self.patches:
            new_tags = {k: v for k, v in w.tags}
            new_tags.update(self.patches[w.id])
            self.writer.add_way(w.replace(tags=new_tags))
        else:
            self.writer.add_way(w)

    def relation(self, r):
        self.writer.add_relation(r)


# ── 메인 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="OSM PBF에 MOCT 속성 패치")
    parser.add_argument("--moct-shp", default=str(MOCT_SHP))
    parser.add_argument("--input",    default=str(OSM_IN))
    parser.add_argument("--output",   default=str(OSM_OUT))
    parser.add_argument("--dry-run",  action="store_true",
                        help="매칭 통계만 출력하고 PBF는 쓰지 않음")
    args = parser.parse_args()

    t0 = time.time()

    # Step 1: MOCT 로드
    moct_geoms, moct_attrs = load_moct(Path(args.moct_shp))

    # Step 2: OSM 매칭
    print(f"\n[2/4] OSM way 매칭 중 (locations=True, 시간 소요 큼)...")
    print(f"      입력: {args.input}")
    handler = MatchHandler(moct_geoms, moct_attrs)
    handler.apply_file(args.input, locations=True, idx="flex_mem")
    handler.stats()
    print(f"      소요: {time.time()-t0:.1f}s")

    if args.dry_run:
        print("\n[dry-run] PBF 작성 생략.")
        _print_sample_patches(handler.patches)
        return

    # Step 3: PBF 출력
    print(f"\n[3/4] 패치된 PBF 작성 중...")
    print(f"      출력: {args.output}")
    writer = osmium.SimpleWriter(args.output, overwrite=True)
    wh = WriteHandler(writer, handler.patches)
    wh.apply_file(args.input)
    writer.close()

    elapsed = time.time() - t0
    print(f"\n[4/4] 완료! 총 소요: {elapsed:.1f}s")
    print(f"      출력 파일: {args.output}")


def _print_sample_patches(patches: dict, n: int = 10):
    print(f"\n패치 샘플 (상위 {n}건):")
    for way_id, tags in list(patches.items())[:n]:
        print(f"  way/{way_id}: {tags}")


if __name__ == "__main__":
    main()

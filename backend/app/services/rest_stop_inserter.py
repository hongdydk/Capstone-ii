import asyncio
import re as _re
from dataclasses import dataclass, field
from math import atan2, cos, degrees, radians, sin, sqrt

# 법정 상수 (변경 금지)
REST_PLAN_SEC: int = 6_000    # 1시간 40분 — 선제적 휴게 삽입 임계값
MAX_DRIVE_SEC: int = 7_200    # 2시간 — 법정 최대 연속 운전
MIN_REST_MIN: int  = 15       # 법정 최소 휴식 시간 (분)

# 긴급 예외 상수 — 화물자동차 운수사업법 시행규칙 [별표3] 다항
# 교통사고·차량고장·교통정체 등 불가피한 사유로 2시간 연속운전 후 휴게 확보가 불가능한 경우
EMERGENCY_EXTEND_SEC: int = 3_600   # 1시간 연장 허용 → 최대 연속 운전 10,800초(3시간)
EMERGENCY_REST_MIN: int   = 30      # 긴급 연장 사용 시 의무 휴식 시간 (분, 일반 15분의 2배)

# Kakao API가 경로를 찾지 못한 구간에 부여하는 대체값 (kakao.py 와 동일)
# 이 값이 행렬에 들어온 구간은 실제 이동이 불가능하므로 누적 운전시간 계산에서 제외
_UNREACHABLE_SEC: int = 10_800_000

# 주요 도시 좌표 — 휴게소 direction 방위각 계산용
_CITY_COORDS: dict[str, tuple[float, float]] = {
    "서울": (37.5665, 126.9780),    "부산": (35.1796, 129.0756),
    "대전": (36.3504, 127.3845),    "대구": (35.8714, 128.6014),
    "광주": (35.1595, 126.8526),    "광주광역시": (35.1595, 126.8526),
    "광주광역": (35.1595, 126.8526), "인천": (37.4563, 126.7052),
    "울산": (35.5384, 129.3114),    "전주": (35.8242, 127.1480),
    "창원": (35.2280, 128.6811),    "포항": (36.0190, 129.3435),
    "목포": (34.8118, 126.3922),    "춘천": (37.8813, 127.7298),
    "강릉": (37.7519, 128.8761),    "양양": (38.0757, 128.6190),
    "순천": (34.9506, 127.4875),    "천안": (36.8151, 127.1139),
    "청주": (36.6424, 127.4890),    "원주": (37.3422, 127.9202),
    "평택": (36.9921, 127.1130),    "당진": (36.8895, 126.6457),
    "공주": (36.4467, 127.1191),    "논산": (36.1878, 127.0994),
    "서천": (36.0797, 126.6919),    "회덕": (36.4226, 127.4086),
    "산내": (35.7183, 127.4956),    "서대전": (36.3298, 127.3878),
    "기장": (35.2445, 129.2226),    "언양": (35.5649, 129.0028),
    "하남": (37.5392, 127.2148),    "통영": (34.8544, 128.4330),
    "세종": (36.4801, 127.2890),    "판교": (37.3943, 127.1106),
    "일산": (37.6566, 126.7722),    "파주": (37.7596, 126.7798),
    "양주": (37.7851, 127.0457),    "구리": (37.5943, 127.1295),
    "포천": (37.8945, 127.2003),    "퇴계원": (37.6552, 127.1744),
    "제천": (37.1329, 128.2138),    "영덕": (36.4153, 129.3649),
    "달서": (35.8310, 128.5320),    "동대구": (35.8795, 128.6284),
    "산인": (35.4283, 128.3411),    "익산": (35.9483, 126.9545),
    "장수": (35.6471, 127.5209),    "새만금": (35.7892, 126.5867),
    "고창": (35.4357, 126.7022),    "담양": (35.3218, 126.9882),
    "삼척": (37.4498, 129.1653),    "속초": (38.2070, 128.5918),
    "양평": (37.4919, 127.4874),
}


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 좌표 간 진북 기준 방위각(0~360도)을 반환합니다."""
    lat1r, lat2r = radians(lat1), radians(lat2)
    dlonr = radians(lon2 - lon1)
    x = sin(dlonr) * cos(lat2r)
    y = cos(lat1r) * sin(lat2r) - sin(lat1r) * cos(lat2r) * cos(dlonr)
    return (degrees(atan2(x, y)) + 360) % 360


def _angle_diff(a: float, b: float) -> float:
    """두 방위각 간 최소 차이(0~180도)."""
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d


def _direction_bearing(direction_str: str | None) -> float | None:
    """'XXX기점 + YYY종점' 문자열로 방위각(도)을 반환합니다. 파싱 불가 시 None."""
    if not direction_str:
        return None
    m = _re.match(r'(.+)기점\s*\+\s*(.+)종점', direction_str)
    if not m:
        return None
    src = m.group(1).strip()
    dst = m.group(2).strip()
    sc = _CITY_COORDS.get(src)
    dc = _CITY_COORDS.get(dst)
    if not sc or not dc:
        return None
    return _bearing(sc[0], sc[1], dc[0], dc[1])


# 한국 중심 좌표 — 이름 기반 방위각 계산 기준점
_KR_CENTER = (36.5, 127.9)


def _name_bearing(name: str) -> float | None:
    """'XX(YYY)휴게소' 이름에서 괄호 안 도시명으로 방위각을 추정합니다.

    truck_rest는 direction 컬럼이 없어도 이름 패턴으로 방향을 구분할 수 있습니다.
    예: '옥천(부산)휴게소' → 부산 방향(남동), '신탄진(서울)휴게소' → 서울 방향(북서)
    """
    if not name:
        return None
    m = _re.search(r'\(([^)]+)\)', name)
    if not m:
        return None
    city = m.group(1).strip()
    dc = _CITY_COORDS.get(city)
    if not dc:
        return None
    # 한국 중심 → 해당 도시 방위각 = 이 차선이 향하는 방향
    return _bearing(_KR_CENTER[0], _KR_CENTER[1], dc[0], dc[1])


@dataclass
class RouteNode:
    type: str   # origin | waypoint | destination | rest_stop
    name: str
    lat: float
    lon: float
    min_rest_minutes: int | None = field(default=None)
    # 경유지는 상·하차 작업 지점 → 법정 휴식 아님 → 기본값 False (누적 운전시간 유지)
    # can_rest=True 가 되는 경우:
    #   1. type='rest_stop' 으로 시스템이 삽입한 휴게소 (호출 측에서 True 명시)
    #   2. 기사가 "여기서 쉼" 을 명시적으로 선택한 경유지 (식당·주유소 등)
    # TODO(상용화): Waypoint 도착 후 실제 체류 시간(dwell_time_min)을 기록해
    #   dwell_time_min >= MIN_REST_MIN(15분) 이면 사후에 누적 운전시간을 보정하는 로직 추가
    can_rest: bool = field(default=False)

    def to_dict(self) -> dict:
        d = {"type": self.type, "name": self.name, "lat": self.lat, "lon": self.lon}
        if self.min_rest_minutes is not None:
            d["min_rest_minutes"] = self.min_rest_minutes
        return d


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 좌표 간 Haversine 직선 거리(미터)를 반환합니다. 후보 필터링 전용."""
    R = 6_371_000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def _haversine_sec(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
    avg_speed_kmh: float = 80.0,
) -> int:
    """Haversine 거리를 속도 기반 시간(초)으로 환산. 후보 필터용 거칠 추정."""
    return int(_haversine_m(lat1, lon1, lat2, lon2) / 1000 / avg_speed_kmh * 3600)


def _project_point_to_segment(
    plat: float, plon: float,
    alat: float, alon: float,
    blat: float, blon: float,
) -> tuple[float, float]:
    """점 P를 선분 AB에 수직투영.

    Returns:
        (t, perp_m)
        t       : 0~1. 선분 AB 위에서의 위치 비율 (A=0, B=1, 선분 밖이면 클램프)
        perp_m  : 점 P와 투영점 사이 거리(m). 한국 영역 평면 근사 사용
    """
    mid_lat = (alat + blat) / 2.0
    mx = 111_320.0 * cos(radians(mid_lat))  # 경도 1° → m
    my = 110_540.0                          # 위도 1° → m

    ax, ay = alon * mx, alat * my
    bx, by = blon * mx, blat * my
    px, py = plon * mx, plat * my

    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        # A == B → 점과 A 사이 거리
        return 0.0, sqrt((px - ax) ** 2 + (py - ay) ** 2)

    t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
    t_clamped = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    proj_x = ax + t_clamped * dx
    proj_y = ay + t_clamped * dy
    perp = sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)
    return t_clamped, perp


def _pick_best_rest(
    prev: RouteNode, nxt: RouteNode, candidates: list[dict]
) -> dict | None:
    """우회 비용(prev → 휴게소 → next) Haversine 최소 후보를 반환합니다.

    주행 방위각과 휴게소 direction 방위각을 비교해 동일 방향(±90°) 후보를 우선합니다.
    highway_rest 우선, 없으면 drowsy_shelter로 폴백합니다.
    """
    travel_brg = _bearing(prev.lat, prev.lon, nxt.lat, nxt.lon)

    def _direction_ok(c: dict) -> bool:
        """방향 데이터 또는 이름 기반으로 주행 방향과 90° 이내인지 확인."""
        db = _direction_bearing(c.get("direction"))
        if db is None:
            db = _name_bearing(c.get("name", ""))  # truck_rest 이름 패턴 폴백
        return db is None or _angle_diff(travel_brg, db) < 90

    def _best_from(pool: list[dict]) -> dict | None:
        best: dict | None = None
        best_cost = float("inf")
        for c in pool:
            if not c.get("is_active", True):
                continue
            cost = (
                _haversine_sec(prev.lat, prev.lon, c["latitude"], c["longitude"])
                + _haversine_sec(c["latitude"], c["longitude"], nxt.lat, nxt.lon)
            )
            if cost < best_cost:
                best_cost = cost
                best = c
        return best

    aligned   = [c for c in candidates if _direction_ok(c)]
    misaligned = [c for c in candidates if not _direction_ok(c)]

    def _is_truck(c: dict) -> bool:
        return c.get("type") == "truck_rest"

    def _is_highway(c: dict) -> bool:
        return c.get("type") == "highway_rest"

    # 1순위: 방향 일치 truck_rest (화물차 전용)
    result = _best_from([c for c in aligned if _is_truck(c)])
    if result:
        return result
    # 2순위: 방향 일치 highway_rest
    result = _best_from([c for c in aligned if _is_highway(c)])
    if result:
        return result
    # 3순위: 방향 일치 drowsy_shelter
    result = _best_from(aligned)
    if result:
        return result
    # 4순위(폴백): 방향 불일치 truck_rest
    result = _best_from([c for c in misaligned if _is_truck(c)])
    if result:
        return result
    # 5순위(폴백): 방향 불일치 highway_rest
    result = _best_from([c for c in misaligned if _is_highway(c)])
    if result:
        return result
    # 6순위(최후 폴백): 방향 불일치 drowsy_shelter
    return _best_from(misaligned)


def _split_polyline_by_ratios(
    polyline: list[list[float]],
    ratios: list[float],
) -> list[list[list[float]]]:
    """폴리라인을 ratios 비율(합=1)로 분할합니다."""
    if len(ratios) == 1:
        return [list(polyline)]

    seg_dists = [
        _haversine_m(polyline[i][0], polyline[i][1], polyline[i + 1][0], polyline[i + 1][1])
        for i in range(len(polyline) - 1)
    ]
    total_dist = sum(seg_dists)
    if total_dist == 0:
        return [list(polyline)] * len(ratios)

    # 분할 목표 누적 거리
    cut_dists: list[float] = []
    cum = 0.0
    for r in ratios[:-1]:
        cum += r * total_dist
        cut_dists.append(cum)

    result: list[list[list[float]]] = []
    current: list[list[float]] = [polyline[0]]
    cut_idx = 0
    cum_dist = 0.0

    for i, d in enumerate(seg_dists):
        while cut_idx < len(cut_dists) and cum_dist + d >= cut_dists[cut_idx]:
            frac = (cut_dists[cut_idx] - cum_dist) / d if d > 0 else 0.0
            clat = polyline[i][0] + frac * (polyline[i + 1][0] - polyline[i][0])
            clon = polyline[i][1] + frac * (polyline[i + 1][1] - polyline[i][1])
            current.append([clat, clon])
            result.append(current)
            current = [[clat, clon]]
            cut_idx += 1
        cum_dist += d
        current.append(polyline[i + 1])

    result.append(current)
    return result


# 휴게소 폴리라인 1차 선별 · GH 2차 우회 비용
_MAX_PERP_M: float = 5_000.0
_PERP_WEIGHT: float = 3.0
_GH_SHORTLIST_K: int = 12


def _leg_for_proj(
    ordered_nodes: list[RouteNode],
    node_projs: list[float],
    target_proj_m: float,
) -> tuple[RouteNode, RouteNode]:
    """이상적 휴게 위치(폴리라인 누적 m)가 속한 구간의 양 끝 노드."""
    for ni in range(len(ordered_nodes) - 1):
        if target_proj_m <= node_projs[ni + 1]:
            return ordered_nodes[ni], ordered_nodes[ni + 1]
    return ordered_nodes[-2], ordered_nodes[-1]


def _shortlist_by_polyline(
    pool: list[dict],
    target_proj_m: float,
    get_proj,
    *,
    k: int = _GH_SHORTLIST_K,
) -> list[dict]:
    """폴리라인 투영 점수 상위 k개 후보 (GH 2차 호출용)."""
    scored: list[tuple[float, dict]] = []
    for c in pool:
        proj_m, perp_m = get_proj(c)
        if perp_m > _MAX_PERP_M:
            continue
        scored.append((abs(proj_m - target_proj_m) + perp_m * _PERP_WEIGHT, c))
    scored.sort(key=lambda x: x[0])
    return [c for _, c in scored[:k]]


def _pick_rest_haversine(
    base: list[dict],
    target_proj_m: float,
    get_proj,
) -> dict | None:
    """Haversine·폴리라인 투영만으로 휴게소 1개 선택 (테스트·GH 폴백)."""

    def _score(c: dict) -> float:
        proj_m, perp_m = get_proj(c)
        if perp_m > _MAX_PERP_M:
            return float("inf")
        return abs(proj_m - target_proj_m) + perp_m * _PERP_WEIGHT

    for type_filter in ("truck_rest", "highway_rest", None):
        pool = [c for c in base if c.get("type") == type_filter] if type_filter else base
        if not pool:
            continue
        cand = min(pool, key=_score)
        if _score(cand) < float("inf"):
            return cand
    return None


async def plan_rest_stops_from_polyline_async(
    ordered_nodes: list[RouteNode],
    polyline: list[list[float]],
    route_time_sec: int,
    rest_candidates: list[dict],
    initial_drive_sec: int = 0,
    is_emergency: bool = False,
    segment_times: list[int] | None = None,
    *,
    profile: str = "truck",
    use_gh: bool = True,
) -> list[RouteNode]:
    """폴리라인 위 이상적 시간 지점에서 휴게소를 선택해 삽입합니다.

    use_gh=True: 폴리라인 상위 K → GraphHopper (prev→휴게→next) 우회 시간 최소.
    use_gh=False: Haversine·폴리라인 투영만 (단위 테스트용).

    segment_times 있을 때 (경유지 존재):
      각 구간(노드→다음 노드)을 독립적으로 평가합니다.
      경유지에서 멈추므로 누적 운전시간을 리셋합니다.

    알고리즘:
      1. (initial_drive_sec + route_time_sec) 를 MAX_DRIVE_SEC 로 나누어 필요 휴게소 수 계산
      2. 폴리라인 위 누적 거리를 평균 속도로 시간 환산 → 이상적 휴게 좌표 추출
      3. 각 이상적 좌표에서 후보 선택 (GH 또는 Haversine)
      4. 폴리라인 투영 거리 기준으로 ordered_nodes 사이 적절한 위치에 삽입
    """
    from app.services import graphhopper as gh_svc

    # ── 경유지 구간 분리 처리 ─────────────────────────────────────────────────
    # 경유지(waypoint)에서 운전자가 멈추므로 구간별 독립 평가
    if (
        segment_times
        and len(segment_times) == len(ordered_nodes) - 1
        and len(ordered_nodes) > 2
    ):
        total_time = sum(t for t in segment_times if t > 0) or 1
        ratios = [max(t, 1) / total_time for t in segment_times]
        rsum = sum(ratios)
        ratios = [r / rsum for r in ratios]
        seg_polys = _split_polyline_by_ratios(polyline, ratios)

        result: list[RouteNode] = []
        used_coords: set[tuple[float, float]] = set()
        accumulated_drive = initial_drive_sec  # 이전 구간에서 이어진 누적 운전시간

        for i in range(len(ordered_nodes) - 1):
            seg_time = segment_times[i]
            seg_poly = seg_polys[i] if i < len(seg_polys) else polyline
            avail = [
                c for c in rest_candidates
                if (c["latitude"], c["longitude"]) not in used_coords
            ]
            # 구간별 재귀 호출 — accumulated_drive 를 initial_drive_sec 로 전달
            seg_result = await plan_rest_stops_from_polyline_async(
                [ordered_nodes[i], ordered_nodes[i + 1]],
                seg_poly,
                seg_time,
                avail,
                initial_drive_sec=accumulated_drive,
                is_emergency=is_emergency,
                profile=profile,
                use_gh=use_gh,
            )

            # ── 경유지 직전 휴게소 이월 처리 ─────────────────────────────────
            # 마지막 구간(목적지 직전)은 이월할 다음 구간이 없으므로 이월하지 않음
            # 마지막 휴게소가 경유지 20분 이내에 삽입됐으면, 경유지를 먼저 방문하고
            # 그 휴게소를 다음 구간 초입으로 미룬다.
            # (실제 법정 시간은 보장: MAX_DRIVE_SEC 초과 전 어차피 다음 구간 직후 삽입)
            _DEFER_THRESH_SEC = 1_200  # 20분
            is_last_segment = (i == len(ordered_nodes) - 2)
            last_rest_node = next(
                (n for n in reversed(seg_result) if n.type == "rest_stop"), None
            )
            deferred_rest: dict | None = None
            if not is_last_segment and last_rest_node is not None:
                time_to_junction = _haversine_sec(
                    last_rest_node.lat, last_rest_node.lon,
                    ordered_nodes[i + 1].lat, ordered_nodes[i + 1].lon,
                )
                if time_to_junction <= _DEFER_THRESH_SEC:
                    # 이 휴게소를 seg_result에서 제거하고 다음 구간으로 이월
                    deferred_rest = {
                        "name": last_rest_node.name,
                        "latitude": last_rest_node.lat,
                        "longitude": last_rest_node.lon,
                        "is_active": True,
                        "direction": None,
                        "type": "truck_rest",
                    }
                    seg_result = [n for n in seg_result if not (
                        n.type == "rest_stop"
                        and n.lat == last_rest_node.lat
                        and n.lon == last_rest_node.lon
                    )]

            for node in seg_result[:-1]:  # 마지막(=다음 구간 시작점) 제외
                if node.type == "rest_stop":
                    used_coords.add((node.lat, node.lon))
                result.append(node)

            # 다음 구간 initial_drive_sec 계산
            n_stops = sum(1 for n in seg_result if n.type == "rest_stop")
            junction = ordered_nodes[i + 1]  # 경유지 or 목적지
            if deferred_rest is not None:
                # 이월된 휴게소: 경유지까지의 운전 시간이 accumulated_drive 에 더해진 상태
                # → 경유지 직후 바로 휴게가 필요하므로 accumulated_drive 를 MAX_DRIVE_SEC 로 세팅
                accumulated_drive = MAX_DRIVE_SEC
                # 이월 휴게소를 다음 구간 avail 최앞에 추가 (우선 선택)
                if deferred_rest not in rest_candidates:
                    rest_candidates = [deferred_rest] + rest_candidates
            elif n_stops > 0:
                # 마지막 휴게소 이후 다음 경유지/목적지까지 Haversine 시간으로 정확히 추정
                last_rest = next(
                    (n for n in reversed(seg_result) if n.type == "rest_stop"),
                    None,
                )
                if last_rest:
                    accumulated_drive = _haversine_sec(
                        last_rest.lat, last_rest.lon,
                        junction.lat, junction.lon,
                    )
                else:
                    accumulated_drive = 0
            elif junction.can_rest:
                # 기사가 명시적으로 휴식 선택한 경유지 → 누적 운전시간 리셋
                accumulated_drive = 0
            else:
                # 상·하차 작업 경유지 (can_rest=False) — 법정 휴식 아님 → 누적 유지
                accumulated_drive += seg_time

        result.append(ordered_nodes[-1])
        return result

    plan_threshold = REST_PLAN_SEC
    rest_minutes = MIN_REST_MIN
    if is_emergency:
        plan_threshold = MAX_DRIVE_SEC + EMERGENCY_EXTEND_SEC
        rest_minutes = EMERGENCY_REST_MIN

    # 법적으로 멈출 필요 없으면 그대로 반환
    if initial_drive_sec + route_time_sec <= MAX_DRIVE_SEC:
        return list(ordered_nodes)

    # 폴리라인 구간별 거리
    if len(polyline) < 2:
        return list(ordered_nodes)

    seg_dists: list[float] = [
        _haversine_m(polyline[i][0], polyline[i][1], polyline[i + 1][0], polyline[i + 1][1])
        for i in range(len(polyline) - 1)
    ]
    total_dist_m = sum(seg_dists)
    if total_dist_m == 0 or route_time_sec == 0:
        return list(ordered_nodes)

    avg_speed_ms = total_dist_m / route_time_sec  # m/s

    def _poly_point(t_sec: float) -> tuple[float, float, float]:
        """경로 시작 후 t_sec 초 지점의 (lat, lon, 방위각)."""
        target = t_sec * avg_speed_ms
        cum = 0.0
        for i, d in enumerate(seg_dists):
            if cum + d >= target:
                ratio = (target - cum) / d if d > 0 else 0.0
                lat = polyline[i][0] + ratio * (polyline[i + 1][0] - polyline[i][0])
                lon = polyline[i][1] + ratio * (polyline[i + 1][1] - polyline[i][1])
                brg = _bearing(polyline[i][0], polyline[i][1], polyline[i + 1][0], polyline[i + 1][1])
                return lat, lon, brg
            cum += d
        brg = _bearing(polyline[-2][0], polyline[-2][1], polyline[-1][0], polyline[-1][1])
        return polyline[-1][0], polyline[-1][1], brg

    # ── 점-선분 수직투영 기반 폴리라인 위치 매핑 ─────────────────────────
    # 좌표를 폴리라인에 투영하면 (누적거리 m, 폴리라인까지 수직거리 m) 가 나옴.
    # 누적거리 → "휴게소가 경로의 어느 시점에 위치하는가" (시간 매핑용)
    # 수직거리 → "휴게소가 도로에서 얼마나 떨어졌는가" (선택 페널티용)
    def _poly_proj(lat: float, lon: float) -> tuple[float, float]:
        cum = 0.0
        best_perp = float("inf")
        best_cum = 0.0
        for i, d in enumerate(seg_dists):
            t, perp = _project_point_to_segment(
                lat, lon,
                polyline[i][0], polyline[i][1],
                polyline[i + 1][0], polyline[i + 1][1],
            )
            if perp < best_perp:
                best_perp = perp
                best_cum = cum + t * d
            cum += d
        return best_cum, best_perp

    # Greedy 삽입: 누적 운전시간이 plan_threshold에 도달하는 지점에서 휴게소 선택.
    selected: list[tuple[float, dict]] = []
    used_coords: set[tuple[float, float]] = set()

    proj_cache: dict[tuple[float, float], tuple[float, float]] = {}

    def _get_proj(c: dict) -> tuple[float, float]:
        key = (c["latitude"], c["longitude"])
        if key not in proj_cache:
            proj_cache[key] = _poly_proj(c["latitude"], c["longitude"])
        return proj_cache[key]

    node_projs = [_poly_proj(n.lat, n.lon)[0] for n in ordered_nodes]

    next_insert_sec: float
    if initial_drive_sec < plan_threshold:
        # 아직 선제 임계값 미달 — plan_threshold까지 남은 시간
        next_insert_sec = float(plan_threshold - initial_drive_sec)
    else:
        # plan_threshold 이미 초과 — 법정 최대(MAX 또는 emergency MAX)까지 남은 시간으로 보정
        # (음수 방지: initial_drive_sec > _legal_max 이면 즉시 삽입)
        _legal_max = (MAX_DRIVE_SEC + EMERGENCY_EXTEND_SEC) if is_emergency else MAX_DRIVE_SEC
        next_insert_sec = max(0.0, float(_legal_max - initial_drive_sec))
    while next_insert_sec < route_time_sec:
        _, _, travel_brg = _poly_point(next_insert_sec)
        target_proj_m = next_insert_sec * avg_speed_ms
        prev_node, nxt_node = _leg_for_proj(ordered_nodes, node_projs, target_proj_m)

        def _dir_ok(c: dict, brg: float = travel_brg) -> bool:
            db = _direction_bearing(c.get("direction"))
            if db is None:
                db = _name_bearing(c.get("name", ""))
            return db is None or _angle_diff(brg, db) < 90

        avail = [
            c for c in rest_candidates
            if c.get("is_active", True)
            and (c["latitude"], c["longitude"]) not in used_coords
        ]
        aligned = [c for c in avail if _dir_ok(c)]
        base = aligned if aligned else avail

        best: dict | None = None
        if base:
            if use_gh:
                shortlist = _shortlist_by_polyline(base, target_proj_m, _get_proj)
                if shortlist:
                    best = await gh_svc.find_best_rest_stop(
                        prev_node, nxt_node, base,
                        profile=profile, shortlist=shortlist,
                    )
            if best is None:
                best = _pick_rest_haversine(base, target_proj_m, _get_proj)

        if best:
            used_coords.add((best["latitude"], best["longitude"]))
            actual_proj, _ = _get_proj(best)
            selected.append((actual_proj, best))
            # 다음 삽입 기준점: 이번 휴게소의 실제 폴리라인 위치 + plan_threshold
            next_insert_sec = actual_proj / avg_speed_ms + plan_threshold
        else:
            next_insert_sec += plan_threshold

    if not selected:
        return list(ordered_nodes)

    # 투영 거리 오름차순으로 ordered_nodes 사이에 삽입
    result: list[RouteNode] = []
    stops_sorted = sorted(selected, key=lambda x: x[0])
    stop_idx = 0

    for ni in range(len(ordered_nodes) - 1):
        result.append(ordered_nodes[ni])
        node_end = node_projs[ni + 1]
        while stop_idx < len(stops_sorted) and stops_sorted[stop_idx][0] <= node_end:
            _, stop = stops_sorted[stop_idx]
            result.append(RouteNode(
                type="rest_stop",
                name=stop["name"],
                lat=stop["latitude"],
                lon=stop["longitude"],
                min_rest_minutes=rest_minutes,
            ))
            stop_idx += 1

    # 미삽입 휴게소는 목적지 직전에 삽입
    for _, stop in stops_sorted[stop_idx:]:
        result.append(RouteNode(
            type="rest_stop",
            name=stop["name"],
            lat=stop["latitude"],
            lon=stop["longitude"],
            min_rest_minutes=rest_minutes,
        ))

    result.append(ordered_nodes[-1])
    return result


def plan_rest_stops_from_polyline(
    ordered_nodes: list[RouteNode],
    polyline: list[list[float]],
    route_time_sec: int,
    rest_candidates: list[dict],
    initial_drive_sec: int = 0,
    is_emergency: bool = False,
    segment_times: list[int] | None = None,
) -> list[RouteNode]:
    """동기 래퍼 — 단위 테스트용 (use_gh=False). API는 async 버전 사용."""
    return asyncio.run(
        plan_rest_stops_from_polyline_async(
            ordered_nodes,
            polyline,
            route_time_sec,
            rest_candidates,
            initial_drive_sec=initial_drive_sec,
            is_emergency=is_emergency,
            segment_times=segment_times,
            use_gh=False,
        )
    )



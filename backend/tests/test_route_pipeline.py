"""
경로 최적화 파이프라인 통합 테스트
TSP 순서 최적화(optimizer) → 휴게소 삽입(rest_stop_inserter) 전 구간 검증
"""
import pytest
from app.services.optimizer import solve_tsp
from app.services.rest_stop_inserter import (
    RouteNode,
    insert_rest_stops,
    REST_PLAN_SEC,
    MAX_DRIVE_SEC,
    EMERGENCY_EXTEND_SEC,
    MIN_REST_MIN,
    EMERGENCY_REST_MIN,
)


# ── 공용 헬퍼 ──────────────────────────────────────────────────

def _make_nodes(n: int) -> list[RouteNode]:
    types = ["origin"] + ["waypoint"] * (n - 2) + ["destination"]
    return [
        RouteNode(type=types[i], name=f"Node{i}", lat=37.0 + i * 0.1, lon=127.0 + i * 0.1)
        for i in range(n)
    ]


def _make_matrix(n: int, seg_time: int) -> list[list[int]]:
    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                matrix[i][j] = seg_time
    return matrix


def _run_pipeline(
    nodes: list[RouteNode],
    matrix: list[list[int]],
    rest_candidates: list[dict],
    *,
    time_limit_seconds: int = 1,
    initial_drive_sec: int = 0,
    is_emergency: bool = False,
) -> list[RouteNode]:
    """TSP → 노드 재정렬 → 휴게소 삽입 파이프라인 실행"""
    tsp_order = solve_tsp(matrix, time_limit_seconds=time_limit_seconds)

    # TSP 결과 순서로 노드 재정렬 (목적지는 항상 마지막)
    destination = nodes[-1]
    ordered = [nodes[i] for i in tsp_order] + [destination]

    # 재정렬 기준으로 시간 행렬도 재구성
    full_order = tsp_order + [len(nodes) - 1]
    n = len(full_order)
    reordered_matrix = [
        [matrix[full_order[i]][full_order[j]] for j in range(n)]
        for i in range(n)
    ]

    return insert_rest_stops(
        ordered,
        reordered_matrix,
        rest_candidates,
        initial_drive_sec=initial_drive_sec,
        is_emergency=is_emergency,
    )


REST_CANDIDATES = [
    {"name": "중부고속도로휴게소", "latitude": 37.25, "longitude": 127.25, "is_active": True},
]


# ── 1. TSP 순서 최적화 검증 ────────────────────────────────────

class TestTspOrdering:
    def test_start_is_always_origin(self):
        """파이프라인 결과의 첫 노드는 반드시 출발지여야 합니다."""
        nodes = _make_nodes(4)
        matrix = _make_matrix(4, 1_000)
        result = _run_pipeline(nodes, matrix, [])
        assert result[0].type == "origin"

    def test_end_is_always_destination(self):
        """파이프라인 결과의 마지막 노드는 반드시 목적지여야 합니다."""
        nodes = _make_nodes(4)
        matrix = _make_matrix(4, 1_000)
        result = _run_pipeline(nodes, matrix, [])
        assert result[-1].type == "destination"

    def test_all_waypoints_included(self):
        """모든 경유지가 결과 경로에 포함되어야 합니다."""
        nodes = _make_nodes(4)  # origin + 2 waypoints + destination
        matrix = _make_matrix(4, 1_000)
        result = _run_pipeline(nodes, matrix, [])
        waypoints = [r for r in result if r.type == "waypoint"]
        assert len(waypoints) == 2

    def test_obvious_optimal_order(self):
        """
        0→1→2→(3) 순서가 명확히 최적인 행렬에서 파이프라인이 올바른 순서를 반환합니다.
        Node1이 Node2보다 먼저 와야 합니다.
        """
        nodes = _make_nodes(4)
        matrix = [
            [0,   1, 100, 1],
            [1,   0,   1, 1],
            [100, 1,   0, 1],
            [1,   1,   1, 0],
        ]
        result = _run_pipeline(nodes, matrix, [])
        non_rest = [r for r in result if r.type != "rest_stop"]
        assert non_rest[0].name == "Node0"   # 출발지
        assert non_rest[1].name == "Node1"   # 최적 경유지 순서
        assert non_rest[2].name == "Node2"
        assert non_rest[-1].name == "Node3"  # 목적지


# ── 2. 휴게소 삽입 검증 ────────────────────────────────────────

class TestRestStopInsertion:
    def test_no_rest_stop_when_short_drive(self):
        """짧은 구간(누적 < 6000초)에서는 휴게소가 삽입되지 않아야 합니다."""
        nodes = _make_nodes(4)
        matrix = _make_matrix(4, 1_000)
        result = _run_pipeline(nodes, matrix, REST_CANDIDATES)
        rest_nodes = [r for r in result if r.type == "rest_stop"]
        assert len(rest_nodes) == 0

    def test_rest_stop_inserted_when_long_segment(self):
        """구간이 REST_PLAN_SEC 이상이면 휴게소가 삽입되어야 합니다."""
        nodes = _make_nodes(4)
        matrix = _make_matrix(4, REST_PLAN_SEC)
        result = _run_pipeline(nodes, matrix, REST_CANDIDATES)
        rest_nodes = [r for r in result if r.type == "rest_stop"]
        assert len(rest_nodes) >= 1

    def test_rest_stop_min_rest_minutes(self):
        """삽입된 휴게소의 min_rest_minutes는 MIN_REST_MIN(15분)이어야 합니다."""
        nodes = _make_nodes(4)
        matrix = _make_matrix(4, REST_PLAN_SEC)
        result = _run_pipeline(nodes, matrix, REST_CANDIDATES)
        rest_nodes = [r for r in result if r.type == "rest_stop"]
        assert all(r.min_rest_minutes == MIN_REST_MIN for r in rest_nodes)

    def test_rest_stop_position_between_waypoints(self):
        """휴게소는 출발지/목적지 사이에 위치해야 합니다."""
        nodes = _make_nodes(4)
        matrix = _make_matrix(4, REST_PLAN_SEC)
        result = _run_pipeline(nodes, matrix, REST_CANDIDATES)
        types = [r.type for r in result]
        assert types[0] == "origin"
        assert types[-1] == "destination"
        assert "rest_stop" in types[1:-1]


# ── 3. 전체 파이프라인 시나리오 ───────────────────────────────

class TestFullPipeline:
    def test_pipeline_structure_no_rest(self):
        """
        짧은 구간 시나리오: origin → waypoints(최적 순서) → destination
        휴게소 없음
        """
        nodes = _make_nodes(4)
        matrix = _make_matrix(4, 500)
        result = _run_pipeline(nodes, matrix, REST_CANDIDATES)
        assert result[0].type == "origin"
        assert result[-1].type == "destination"
        assert all(r.type != "rest_stop" for r in result)

    def test_pipeline_structure_with_rest(self):
        """
        긴 구간 시나리오: origin → ... → rest_stop → ... → destination
        TSP 최적화 후 휴게소 포함
        """
        nodes = _make_nodes(4)
        matrix = _make_matrix(4, REST_PLAN_SEC)
        result = _run_pipeline(nodes, matrix, REST_CANDIDATES)
        assert result[0].type == "origin"
        assert result[-1].type == "destination"
        assert any(r.type == "rest_stop" for r in result)

    def test_emergency_pipeline(self):
        """
        긴급 모드: 삽입된 휴게소의 휴식 시간은 EMERGENCY_REST_MIN(30분)이어야 합니다.
        일반 모드(15분)와의 차이를 파이프라인 전체 흐름에서 검증합니다.
        """
        nodes = _make_nodes(4)
        matrix = _make_matrix(4, REST_PLAN_SEC)

        normal_result = _run_pipeline(nodes, matrix, REST_CANDIDATES, is_emergency=False)
        emergency_result = _run_pipeline(nodes, matrix, REST_CANDIDATES, is_emergency=True)

        normal_rests = [r for r in normal_result if r.type == "rest_stop"]
        emergency_rests = [r for r in emergency_result if r.type == "rest_stop"]

        # 일반 모드: 15분 휴식
        assert all(r.min_rest_minutes == MIN_REST_MIN for r in normal_rests)
        # 긴급 모드: 30분 휴식
        assert all(r.min_rest_minutes == EMERGENCY_REST_MIN for r in emergency_rests)

    def test_initial_drive_sec_triggers_early_rest(self):
        """
        초기 누적 운전 시간이 있으면 더 일찍 휴게소가 삽입됩니다.
        """
        nodes = _make_nodes(4)
        matrix = _make_matrix(4, 1_000)
        # 초기 누적 5500초 → 첫 구간(1000초) 후 합계 6500 > 6000
        result = _run_pipeline(nodes, matrix, REST_CANDIDATES, initial_drive_sec=5_500)
        rest_nodes = [r for r in result if r.type == "rest_stop"]
        assert len(rest_nodes) >= 1

    def test_no_candidates_no_rest_even_if_long(self):
        """
        휴게소 후보가 없으면 구간이 길어도 삽입하지 않습니다.
        """
        nodes = _make_nodes(4)
        matrix = _make_matrix(4, REST_PLAN_SEC)
        result = _run_pipeline(nodes, matrix, rest_candidates=[])
        rest_nodes = [r for r in result if r.type == "rest_stop"]
        assert len(rest_nodes) == 0

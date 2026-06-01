"""cargo_id 기반 pickup→delivery 쌍 생성 및 replan TSP 제약 검증."""
from app.api.optimize import _build_cargo_pickup_deliveries
from app.services.optimizer import solve_tsp


def test_build_cargo_pairs_1_to_n():
    wps = [
        {"cargo_id": "A", "cargo_role": "pickup"},
        {"cargo_id": "A", "cargo_role": "delivery"},
        {"cargo_id": "A", "cargo_role": "delivery"},
    ]
    pairs = _build_cargo_pickup_deliveries(wps, start_index=1)
    assert pairs == [(1, 2), (1, 3)]


def test_build_cargo_pairs_stop_type_fallback():
    wps = [
        {"cargo_id": "B", "stop_type": "pickup"},
        {"cargo_id": "B", "stop_type": "delivery"},
    ]
    pairs = _build_cargo_pickup_deliveries(wps, start_index=1)
    assert pairs == [(1, 2)]


def test_replan_style_pickup_before_delivery():
    """replan 노드 구성: 0=현재위치, 1=pickup, 2=delivery, 3=목적지."""
    matrix = [
        [0, 100, 200, 50],
        [100, 0, 100, 100],
        [200, 100, 0, 100],
        [50, 100, 100, 0],
    ]
    pairs = _build_cargo_pickup_deliveries(
        [
            {"cargo_id": "A", "cargo_role": "pickup"},
            {"cargo_id": "A", "cargo_role": "delivery"},
        ],
        start_index=1,
    )
    order = solve_tsp(matrix, pickup_deliveries=pairs)
    assert order is not None
    assert order.index(1) < order.index(2)

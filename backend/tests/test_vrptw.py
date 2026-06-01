"""VRPTW(solve_vrptw) 단위 테스트 — PLAN Phase 0: unassigned·해 탐색 고정."""
import pytest

from app.services.optimizer import solve_vrptw, solve_vrptw_with_vehicle_end_policy


def _uniform_matrix(n: int, off_diagonal: int) -> list[list[int]]:
    m = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                m[i][j] = off_diagonal
    return m


class TestSolveVrptw:
    def test_two_vehicles_all_nodes_served(self):
        """2대·2배송지: 완화된 시간창이면 전 노드가 어느 차량에든 배정된다."""
        tm = _uniform_matrix(3, 600)  # depot + 2 nodes, 10분 이동
        tw = [(0, 99_999), (0, 99_999), (0, 99_999)]
        out = solve_vrptw(
            tm,
            num_vehicles=2,
            time_windows=tw,
            time_limit_seconds=5,
        )
        assert out is not None
        routes, unserved = out
        assert unserved == []
        served = sorted({n for r in routes for n in r})
        assert served == [1, 2]

    def test_unserved_when_time_window_too_tight(self):
        """이동시간보다 짧은 시간창이면 일부 노드는 미배정(disjunction)될 수 있다."""
        tm = _uniform_matrix(4, 3_600)  # depot + 3 nodes, 60분 이동
        # depot 무제한, 고객은 모두 [0, 1800] = 30분 이내 도착만 허용 → 60분 이동이면 단독 방문 불가
        _inf = 999_999_999
        tw = [(0, _inf), (0, 1_800), (0, 1_800), (0, 1_800)]
        out = solve_vrptw(
            tm,
            num_vehicles=2,
            time_windows=tw,
            time_limit_seconds=10,
        )
        assert out is not None
        _routes, unserved = out
        assert len(unserved) >= 1, "전부 배정되면 시간창·페널티 설정이 테스트 의도와 다름"

    def test_vrptw_with_capacity_splits_demand(self):
        """용량 제약 시 일부는 unserved일 수 있다."""
        tm = _uniform_matrix(3, 100)  # 2 고객
        tw = [(0, 99_999)] * 3
        # 차량 1대, 용량 5, 수요 각 4 → 합 8 > 5 → 한 건은 드롭
        caps = [5]
        demands = [0, 4, 4]
        out = solve_vrptw(
            tm,
            num_vehicles=1,
            vehicle_capacities=caps,
            demands=demands,
            time_windows=tw,
            time_limit_seconds=10,
        )
        assert out is not None
        routes, unserved = out
        assert len(unserved) >= 1


class TestSolveVrptwWithVehicleEndPolicy:
    def test_return_to_depot_and_open_end_choose_different_order(self):
        """복귀 비용이 큰 고객은 open_end에서 마지막 방문지로 남을 수 있다."""
        tm = [
            [0, 1, 1],
            [1, 0, 1],
            [100, 2, 0],
        ]

        return_out = solve_vrptw_with_vehicle_end_policy(
            tm,
            starts=[0],
            end_policies="return_to_depot",
            time_limit_seconds=5,
        )
        open_out = solve_vrptw_with_vehicle_end_policy(
            tm,
            starts=[0],
            end_policies="open_end",
            time_limit_seconds=5,
        )

        assert return_out is not None
        assert open_out is not None
        return_routes, return_unserved = return_out
        open_routes, open_unserved = open_out
        assert return_unserved == []
        assert open_unserved == []
        assert return_routes == [[2, 1]]
        assert open_routes == [[1, 2]]

    def test_capacity_unserved_behavior_is_preserved(self):
        """새 solver에서도 용량 초과 노드는 disjunction으로 미배정될 수 있다."""
        tm = _uniform_matrix(3, 100)
        tw = [(0, 99_999)] * 3
        demands = [0, 4, 4]

        out = solve_vrptw_with_vehicle_end_policy(
            tm,
            starts=[0],
            end_policies="open_end",
            vehicle_capacities=[5],
            demands=demands,
            time_windows=tw,
            time_limit_seconds=10,
        )

        assert out is not None
        routes, unserved = out
        assert len(routes) == 1
        assert len(unserved) >= 1
        served_demand = sum(demands[node] for route in routes for node in route)
        assert served_demand <= 5

    def test_open_end_non_depot_start_excludes_depot_from_results(self):
        """open_end에서 depot이 차량 start가 아니어도 고객/미배정으로 노출되지 않는다."""
        tm = [
            [0, 1000, 1000, 1000],
            [1000, 0, 1, 1],
            [1000, 1, 0, 1],
            [1000, 1, 1, 0],
        ]

        out = solve_vrptw_with_vehicle_end_policy(
            tm,
            starts=[1],
            end_policies="open_end",
            depot=0,
            time_limit_seconds=5,
        )

        assert out is not None
        routes, unserved = out
        served = {node for route in routes for node in route}
        assert 0 not in served
        assert 0 not in unserved
        assert 1 not in served
        assert 1 not in unserved
        assert sorted(served | set(unserved)) == [2, 3]

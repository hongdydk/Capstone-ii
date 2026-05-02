from ortools.constraint_solver import pywrapcp, routing_enums_pb2


def validate_tsp_constraints(
    time_matrix: list[list[int]],
    time_windows: list[tuple[int, int]] | None = None,
    pickup_deliveries: list[tuple[int, int]] | None = None,
    node_names: list[str] | None = None,
) -> tuple[int, str] | None:
    """
    OR-Tools 호출 전 제약 충돌을 사전에 검사합니다.

    Returns:
        (http_status_code, detail_message) — 충돌 발견 시
        None                               — 이상 없음
    """
    n = len(time_matrix)
    names = node_names or [f"노드{i}" for i in range(n)]

    if time_windows:
        # 1. 시간창 역전 (최소 > 최대) — 입력 오류 → 400
        for i, (earliest, latest) in enumerate(time_windows):
            if earliest > latest:
                return (
                    400,
                    f"시간창 역전: '{names[i]}'의 최소 도착 시각({earliest // 60}분)이 "
                    f"최대 도착 시각({latest // 60}분)보다 큽니다.",
                )

        # 2. 출발지→노드 직행 이동 시간이 시간창 최대치 초과 — 물리적 불가능 → 422
        for i, (_, latest) in enumerate(time_windows):
            if i == 0:
                continue  # 출발지 자신은 제외
            min_travel = time_matrix[0][i]
            if min_travel > latest:
                return (
                    422,
                    f"이동 시간 초과: 출발지에서 '{names[i]}'까지 최소 {min_travel // 60}분 소요, "
                    f"허용 최대 도착 시각은 {latest // 60}분입니다.",
                )

    # 3. 상차→하차 쌍의 시간창 충돌 — 상차 최조 도착 + 이동시간 > 하차 최대 도착 → 422
    if time_windows and pickup_deliveries:
        for pickup_node, delivery_node in pickup_deliveries:
            if pickup_node in (0, n - 1) or delivery_node in (0, n - 1):
                continue
            pu_earliest = time_windows[pickup_node][0]
            dl_latest = time_windows[delivery_node][1]
            travel = time_matrix[pickup_node][delivery_node]
            if pu_earliest + travel > dl_latest:
                return (
                    422,
                    f"상차→하차 시간 충돌: '{names[pickup_node]}' 상차 최조 도착 {pu_earliest // 60}분 + "
                    f"이동 {travel // 60}분이 '{names[delivery_node]}' 최대 도착 시각 {dl_latest // 60}분을 초과합니다.",
                )

    return None


def solve_tsp(
    time_matrix: list[list[int]],
    *,
    time_limit_seconds: int = 10,
    time_windows: list[tuple[int, int]] | None = None,
    pickup_deliveries: list[tuple[int, int]] | None = None,
) -> list[int] | None:
    """
    OR-Tools TSP로 경유지 방문 순서를 최적화합니다.

    - 인덱스 0: 출발지 (고정)
    - 인덱스 1 ~ n-2: 최적화 대상 경유지
    - 인덱스 n-1: 목적지 (고정 — 마지막 방문)

    Args:
        time_matrix        : NxN 이동 시간 행렬 (초 단위)
        time_limit_seconds : OR-Tools 탐색 시간 제한
        time_windows       : 노드별 도착 허용 시간 범위 [(earliest_sec, latest_sec), ...]
                             None 이면 시간 제약 없음. 단위는 출발 기준 경과 초.
        pickup_deliveries  : 상차→하차 순서 쌍 [(pickup_idx, delivery_idx), ...]
                             pickup_idx 노드가 반드시 delivery_idx 보다 먼저 방문됨.

    Returns:
        최적 방문 인덱스 목록 (0번 출발지 포함, n-1번 목적지 제외)
    """
    n = len(time_matrix)
    if n <= 2:
        return list(range(n))

    # 목적지를 end depot으로 고정
    manager = pywrapcp.RoutingIndexManager(n, 1, [0], [n - 1])
    routing = pywrapcp.RoutingModel(manager)

    def transit_callback(from_index: int, to_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return time_matrix[from_node][to_node]

    transit_id = routing.RegisterTransitCallback(transit_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_id)

    # ── Time Window 제약 ──────────────────────────────────────────────────
    if time_windows or pickup_deliveries:
        # 최대 가능 시간 = 모든 구간 합산 (상한으로 사용)
        max_horizon = sum(max(row) for row in time_matrix)
        routing.AddDimension(
            transit_id,
            slack_max=max_horizon,   # 대기 허용 시간 상한
            capacity=max_horizon,    # 누적 시간 상한
            fix_start_cumul_to_zero=True,
            name="Time",
        )
        time_dim = routing.GetDimensionOrDie("Time")

        if time_windows:
            for node_idx, (earliest, latest) in enumerate(time_windows):
                routing_idx = manager.NodeToIndex(node_idx)
                time_dim.CumulVar(routing_idx).SetRange(earliest, latest)

        # ── Pickup → Delivery 순서 제약 ───────────────────────────────────
        if pickup_deliveries:
            for pickup_node, delivery_node in pickup_deliveries:
                # 출발지(0)는 start depot — AddPickupAndDelivery에 넣으면
                # OR-Tools 내부 크래시 발생. 출발지는 항상 첫 방문이므로
                # 상차지==0 쌍은 제약 추가를 건너뜁니다.
                if pickup_node == 0:
                    continue
                # 목적지(n-1)는 end depot — pickup/delivery 어느 쪽에도 넣으면 크래시
                if pickup_node == n - 1:
                    continue
                if delivery_node == n - 1:
                    continue
                # 출발지(0)를 delivery로 쓰는 것도 불가
                if delivery_node == 0:
                    continue
                pickup_idx   = manager.NodeToIndex(pickup_node)
                delivery_idx = manager.NodeToIndex(delivery_node)
                routing.AddPickupAndDelivery(pickup_idx, delivery_idx)
                routing.solver().Add(
                    routing.VehicleVar(pickup_idx) == routing.VehicleVar(delivery_idx)
                )
                # 상차 누적시간 ≤ 하차 누적시간 강제
                routing.solver().Add(
                    time_dim.CumulVar(pickup_idx) <= time_dim.CumulVar(delivery_idx)
                )

    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_params.time_limit.seconds = time_limit_seconds

    solution = routing.SolveWithParameters(search_params)
    if not solution:
        # 시간 제약 또는 pickup_delivery 제약과 순서 제약이 충돌해 해 없음 → None 반환
        return None

    route: list[int] = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        route.append(manager.IndexToNode(index))
        index = solution.Value(routing.NextVar(index))

    return route

from ortools.constraint_solver import pywrapcp, routing_enums_pb2


def solve_tsp(time_matrix: list[list[int]], *, time_limit_seconds: int = 10) -> list[int]:
    """
    OR-Tools TSP로 경유지 방문 순서를 최적화합니다.

    - 인덱스 0: 출발지 (고정)
    - 인덱스 1 ~ n-2: 최적화 대상 경유지
    - 인덱스 n-1: 목적지 (고정 — 마지막 방문)

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
        # 해 없으면 입력 순서 그대로 반환
        return list(range(n))

    route: list[int] = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        route.append(manager.IndexToNode(index))
        index = solution.Value(routing.NextVar(index))

    return route

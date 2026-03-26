DEFAULT_CASES   = 100
DEFAULT_SEED    = 42
DEFAULT_MAX_WPS = 5


def pytest_addoption(parser):
    parser.addoption("--cases",     action="store", default=DEFAULT_CASES,    type=int)
    parser.addoption("--seed",      action="store", default=DEFAULT_SEED,     type=int)
    parser.addoption("--max-nodes", action="store", default=DEFAULT_MAX_WPS,  type=int)
    parser.addoption(
        "--offline",
        action="store_true",
        default=False,
        help="TMAP API 호출 없이 Haversine + 주소 근사 좌표로 실행 (API 한도 초과 시)",
    )

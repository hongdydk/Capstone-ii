# RouteOn (루트온) — Copilot 지침

화물차 법정 휴게 규정 자동 반영 경로 최적화 API 서버.

## 아키텍처

- **백엔드**: FastAPI + SQLAlchemy 2.x async + PostgreSQL (asyncpg)
- **최적화 파이프라인**: Kakao Mobility API(N²-N 동시 호출) → OR-Tools TSP → 휴게소 삽입
- **프론트 2종**: 관제 웹(admin 전용), 기사 앱(driver · contractor 공용)

주요 경계:
| 모듈 | 역할 |
|---|---|
| `backend/app/services/kakao.py` | Kakao Mobility API — `departure_time` 없으면 다중 목적지 API(N회), 있으면 Future Directions 개별 호출(N²-N회) |
| `backend/app/services/optimizer.py` | OR-Tools TSP — index 0 출발지 고정, index n-1 목적지 고정 |
| `backend/app/services/rest_stop_inserter.py` | 법정 휴게소 삽입 — REST_PLAN_SEC=6000초 임계값 |
| `backend/app/models/` | SQLAlchemy Mapped 모델 — `SCHEMA.md`와 1:1 대응 |
| `backend/app/schemas/optimize.py` | `RouteNodeSchema` — `optimized_route` JSONB 구조 정의 |

## 법적 상수 (변경 금지)

```python
REST_PLAN_SEC        = 6_000   # 1시간 40분 — 선제적 휴게 삽입 임계값
MAX_DRIVE_SEC        = 7_200   # 2시간 — 법정 최대 연속 운전
MIN_REST_MIN         = 15      # 법정 최소 휴식 시간 (분)
EMERGENCY_EXTEND_SEC = 3_600   # 긴급 예외(다항) — 1시간 연장, 최대 3시간 연속 운전
EMERGENCY_REST_MIN   = 30      # 긴급 예외(다항) — 의무 휴식 30분
```

## 빌드 및 실행

```bash
# Docker (권장)
docker compose up -d

# 로컬 개발
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 졸음쉼터 CSV 시드 (EUC-KR 인코딩 자동 처리)
python backend/seeds/seed_rest_stops.py
```

API: http://localhost:8000 | Swagger: http://localhost:8000/docs

## 환경 변수 (`backend/.env`)

| 키 | 설명 |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://routeon:routeon@localhost:5432/routeon` |
| `KAKAO_API_KEY` | Kakao Developers 앱 키 — [developers.kakao.com](https://developers.kakao.com) |
| `SECRET_KEY` | JWT 서명 키 (운영 시 반드시 교체) |
| `DEBUG` | `true`이면 SQLAlchemy echo 활성화 |

## 컨벤션

- **DB 스키마 변경 시** `SCHEMA.md`와 `backend/seeds/init_tables.sql`을 동시에 업데이트
- **새 API 엔드포인트**는 `backend/app/api/`에 라우터 파일 추가 후 `main.py`에 등록
- **의존성 주입**: DB 세션은 `get_db()` 사용 — `AsyncSession`을 직접 생성하지 말 것
- **Kakao 좌표 순서**: API 파라미터는 `{lon},{lat}` 순서 (경도 먼저)
- **JSONB 필드** (`waypoints`, `optimized_route`): `RouteNodeSchema` Pydantic 모델로 검증
- CSV 인코딩: `자료/` 폴더의 한국도로공사 파일은 `encoding='euc-kr'`

## 주의사항

- Kakao Mobility API 무료 플랜 **10 QPS** 제한 — 경유지 4개(노드 6개 = 30호출) 초과 시 `429` 발생 가능
- `departure_time` 있으면 Future Directions API (`/v1/future/directions`), 없으면 실시간 (`/v1/directions`)
- `SECRET_KEY` 기본값 `CHANGE_ME_IN_PRODUCTION`은 운영 배포 전 반드시 교체할 것

## 참고 문서

- 전체 DB 스키마: [`SCHEMA.md`](../SCHEMA.md)
- 프로젝트 개요 및 API 예시: [`ReadMe.md`](../ReadMe.md)
- 테이블 DDL: [`backend/seeds/init_tables.sql`](../backend/seeds/init_tables.sql)

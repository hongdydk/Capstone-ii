# RouteOn (루트온)

화물 운행 경로 최적화 백엔드와, **지입기사 콜 배차** 및 **기사 앱 자체 내비게이션** 개발을 목표로 하는 프로젝트입니다.  
제품·기술 방향은 [PLAN.md](PLAN.md)를 기준으로 한다.

## 1) 현재 데모 범위

- 단건 최적화: `POST /optimize/`
- 운행 중 재탐색: `POST /optimize/replan`
- DB 없는 데모: `POST /demo/route`

## 2) 빠른 실행 (로컬)

### 필수
- Python 3.11+
- PostgreSQL 14+
- Java 21+ (GraphHopper)

### 백엔드
```bash
cd backend
python -m venv ../.venv
# Windows PowerShell
../.venv/Scripts/Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### GraphHopper
```bash
cd Engine
java -Xmx4g -jar graphhopper-web-11.0.jar server config.yml
```

접속:
- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`

## 3) 핵심 API 계약 (요약)

- 클라이언트 계약 중심은 `route[]` 순서와 각 노드의 `lat`, `lon`
- `polyline`은 있더라도 디버그/보조 필드
- 상·하차 제약은 `cargo_id` + `cargo_role` (`pickup` / `delivery`)
- `replan`의 `remaining_waypoints`에도 동일 계약 적용

상세 필드/타입/요청·응답은 `SCHEMA.md`와 Swagger(` /docs `)를 기준으로 확인합니다.

## 4) 목업/테스트 경로

- 관제 웹: OSM 기반 지도·콜 배차 UI — 저장소·경로 `[TBD]` (기존 `frontend_Test/` 정적 목업은 제거됨)
- 백엔드 소스: `backend/app/`
- 최적화 핵심 로직: `backend/app/services/`

## 5) 문서 역할

- `README.md`: 개요, 실행, 데모 범위, 진입점
- `ARCHITECTURE.md`: 백엔드 레이어·최적화 파이프라인·상태 전이·리팩터 로드맵
- `PLAN.md`: 제품·기술 방향, 콜 배차·자체 내비 축, 미확정(TBD) 항목
- `SCHEMA.md`: 데이터/API 계약 단일 출처
- `BUGREPORT.md`: 운영·알고리즘 이슈 백로그(P0–P3), 팀장 결정용 선택지·권장
- `CHANGELOG.md`: 전체 커밋 히스토리

운영 배포는 Oracle Cloud + Docker(컨테이너 네트워크) 기준이며, GraphHopper는 `Engine/` 이미지·`GH_BASE` 환경 변수로 연동한다. 백로그 요약은 `PLAN.md` §8, 상세는 [BUGREPORT.md](BUGREPORT.md).

## 6) Roadmap (아주 짧게)

- **콜 배차:** 관제에서 콜 생성 → 기사 앱 **콜 목록** 노출 → 수락/거절 → 배정·운행 (상세는 `PLAN.md`)
- **자체 내비:** 기사 앱에서 `/optimize`·`replan`의 `route[]`·`polyline`으로 **OSM 기반** 지도·경로·턴-by-turn 안내 구현 (관제 웹도 OSM 기반 지도로 모니터링 전용)
- 기존 최적화·`replan` API는 유지·연동 (세부 API 변경은 팀장 확정 후)


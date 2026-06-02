# RouteOn (루트온)

화물 운행 경로를 최적화하고 법정 휴게 규정을 반영하는 백엔드 중심 프로젝트입니다.  
현재 저장소는 **발표 직전 데모 기준**으로 문서를 최소화해 유지합니다.

## 1) 현재 데모 범위

- 단건 최적화: `POST /optimize/`
- 운행 중 재탐색: `POST /optimize/replan`
- DB 없는 데모: `POST /demo/route`
- 다차량 배차 계산 응답: `POST /optimize/dispatch`  
  (계산 응답 중심, 배차 결과 영속화는 후속 범위)

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

- 관제 웹 목업: `frontend_Test/control_app_mockup_light.html`
- 백엔드 소스: `backend/app/`
- 최적화 핵심 로직: `backend/app/services/`

## 5) 문서 역할

- `README.md`: 개요, 실행, 데모 범위, 진입점
- `SCHEMA.md`: 데이터/API 계약 단일 출처
- `DEPLOY.md`: 배포/운영 절차
- `CHANGELOG.md`: 전체 커밋 히스토리

## 6) Roadmap (아주 짧게)

- `POST /optimize/dispatch` 결과의 DB 영속화(DispatchGroup/Trip 연계)
- 배차 결과 전달/운영 플로우 고도화


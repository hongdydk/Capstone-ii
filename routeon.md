Claude.md — 루트온(RouteOn) Claude Prompting Guide
이 파일을 대화 시작 시 첨부하면 Claude가 프로젝트 맥락을 즉시 파악합니다.

프로젝트 기본 정보
프로젝트명: 루트온 (RouteOn)
설명: 화물차 법정 휴게 규정 자동 반영 + 다중 경유지 경로 최적화 + 휴식 포인트 추천 서비스
팀 역할
이름	담당
어진	백엔드 (FastAPI) + 관리자 웹 + Docker 인프라
팀원 A	제약 알고리즘 + 앱
팀원 B	앱
기술 스택
분류	기술
백엔드	Python 3.12 + FastAPI (비동기)
DB	PostgreSQL 16 + TimescaleDB, Redis
지도	카카오맵 SDK (관리자 웹), 카카오 모빌리티 API (경로 최적화)
최적화	Google OR-Tools (TSP)
인프라	Docker Compose, Nginx, Oracle Cloud
앱	Android Studio (Kotlin)
관리자 웹	HTML/JS (바닐라)
서버 정보
항목	값
서버 IP	168.138.45.63
FastAPI	http://168.138.45.63:8000
Swagger	http://168.138.45.63:8000/docs
관리자 웹	http://168.138.45.63:3000
code-server	http://168.138.45.63:8443
프로젝트 경로	/opt/routeon/
디렉터리 구조
routeon/
├── Claude.md
├── DB_SCHEMA.md
├── CHANGELOG.md
├── docker-compose.yml
├── nginx.conf
├── .env
├── .env.example
├── docs/
│   └── Rest.txt
├── backend/
│   ├── main.py             FastAPI 앱 — 모든 API 엔드포인트 (단일 파일)
│   ├── auth.py             JWT 인증 (비동기)
│   ├── database.py         DB 연결 — AsyncEngine, AsyncSession
│   ├── models.py           DB 테이블
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── uploads/            기업 등록 서류 업로드 저장소
│   ├── services/
│   │   ├── kakao_mobility.py      카카오 모빌리티 API + TTL 캐시 + find_best_rest_stop
│   │   ├── optimizer.py           OR-Tools TSP
│   │   ├── email_service.py       기업 승인/반려 이메일 알림
│   │   └── rest_stop_inserter.py  법정 휴게 규정 기반 휴게소 자동 삽입 (async)
│   └── seeds/
│       ├── seed_rest_stops.py     졸음쉼터 CSV → DB 삽입 (253건 완료)
│       ├── inspect_files.py       파일 컬럼 확인
│       └── 한국도로공사_졸음쉼터_20260225.csv
└── frontend/
    ├── index.html          랜딩 페이지
    ├── intro.html          서비스 소개
    ├── login.html
    ├── register.html       기업 등록 (사업자등록증 업로드 포함)
    ├── dashboard.html      관리자 대시보드 (카카오맵 + 실시간 위치 + 경로선)
    └── superadmin.html     슈퍼 관리자 (기업 심사)
컨테이너
컨테이너	포트	설명
routeon-db	5432	PostgreSQL + TimescaleDB
routeon-api	8000	FastAPI 백엔드
routeon-redis	6379	Redis (GPS TTL 5분)
routeon-frontend	3000	Nginx + 관리자 웹
routeon-code-server	8443	브라우저 VS Code
핵심 원칙
좌표 필드명
위도: lat
경도: lon (lng 절대 금지 — 팀원 A 코드와 통일)
예외: rest_stops 테이블만 latitude / longitude 사용
비동기 패턴
result = await db.execute(select(Model).where(Model.id == id))
obj    = result.scalar_one_or_none()
db.add(obj)
await db.commit()
await db.refresh(obj)
경로 최적화 파이프라인
1. 관리자: POST /trips → 경유지·목적지 등록
2. 기사:   POST /optimize → trip_id + 출발지
           └─ auto_detect_route_mode() — 50km 기준 local/long_distance
           └─ 카카오 모빌리티 N×N (시간·거리 행렬) — TTL 캐시 1시간
           └─ OR-Tools TSP 경유지 순서 최적화
           └─ insert_rest_stops() — 6,000초 임계값 + find_best_rest_stop() picker
           └─ total_distance_km + estimated_duration_min 포함 응답
           └─ trip.status → in_progress 변경
3. 기사:   POST /optimize/replan → 운행 중 재경로
원격 배차 (경유지 추가) 흐름
관리자 웹: 기사 카드 선택 → 이름 + 주소 입력 → 운행 목록에 추가 클릭
→ GET /address/coord         주소 → 좌표 변환
→ PATCH /trips/{id}/waypoints trips.waypoints에 경유지 추가 + DB 저장
→ WS broadcast               기사 앱에 replan_requested 알림 전송
→ 기사 앱: POST /optimize/replan 호출 → 새 경로 수신
WS 메시지 형식 (replan_requested)
{
  "type": "replan_requested",
  "trip_id": "uuid",
  "driver_id": "uuid",
  "new_waypoint": {"name": "추가경유지", "lat": 36.0, "lon": 127.8},
  "waypoints": [...],
  "message": "새 경유지가 추가됐습니다. 경로를 재계산하세요."
}
GPS 흐름
Android 앱 → POST /location-logs (5초 주기) → Redis(TTL 5분)
                                             → locations(TimescaleDB 7일)
                                             → 50m 도착 감지 → Delivery.done
                                             → WS broadcast → 관리자 웹 마커
관리자 웹  → WS /ws/location → 실시간 수신 → 지도 마커 업데이트
관리자 웹  → GET /location-logs/{user_id} → Redis 현재 위치
관리자 웹 경로선
기사 카드 클릭
→ GET /trips?driver_id={id}&status=in_progress
→ GET /trips/{id}/polyline → 카카오 모빌리티 실제 도로 좌표
→ 카카오맵에 파란 경로선 + 노드 마커(🏁📦☕🏴) 표시
Trip status 값
값	의미	변경 시점
scheduled	배차 완료, 출발 전	POST /trips 생성 시 기본값
in_progress	운행 중	POST /optimize 호출 시 자동 변경
completed	운행 완료	PATCH /trips/{id}/status?status=completed
cancelled	취소	PATCH /trips/{id}/status?status=cancelled
기업(Organization) 상태 값
값	의미
pending_review	등록 후 슈퍼 관리자 심사 대기
approved	승인 완료 — 서비스 이용 가능
rejected	반려 (reject_reason 참고)
API 전체 목록
공통
엔드포인트	권한	설명
GET /health	없음	서버 상태
GET /config	없음	카카오 JS 키 반환
인증
엔드포인트	권한	설명
POST /auth/register	없음	기사 가입 (조직코드 필수, pending 처리)
POST /auth/login	없음	로그인 → JWT
GET /auth/me	로그인	내 정보
PATCH /auth/me	로그인	전화번호/비밀번호 변경
GET /auth/check-username	없음	아이디 중복 확인
POST /auth/approve/{id}	관리자	같은 기업 기사 승인
유저/차량
엔드포인트	권한	설명
GET /users?role=driver	관리자	같은 기업 유저 목록
DELETE /users/{id}	관리자	유저 삭제
GET /vehicles	관리자	차량 목록
POST /vehicles	관리자	차량 등록
DELETE /vehicles/{id}	관리자	차량 비활성화
기업(Organizations)
엔드포인트	권한	설명
POST /organizations	없음	기업 등록 + 관리자 계정 생성 (사업자서류 첨부 필수)
GET /organizations/me	관리자	내 기업 정보 + 조직코드 조회
POST /organizations/regen-code	관리자	조직코드 재발급
GET /organizations/lookup?org_code=	없음	조직코드로 기업명 조회
슈퍼 관리자 (superadmin)
엔드포인트	권한	설명
GET /superadmin/organizations	슈퍼관리자	전체 기업 목록 (?status=pending_review|approved|rejected)
GET /superadmin/organizations/{id}/doc	슈퍼관리자	기업 첨부 서류 다운로드
POST /superadmin/organizations/{id}/approve	슈퍼관리자	기업 승인 + 이메일 알림
POST /superadmin/organizations/{id}/reject	슈퍼관리자	기업 반려 + 사유 저장 + 이메일 알림
POST /superadmin/create-account	슈퍼관리자	계정 직접 생성
운행/경로
엔드포인트	권한	설명
GET /rest-stops	없음	휴게소 목록
POST /rest-stops	관리자	휴게소 등록
DELETE /rest-stops/{id}	관리자	휴게소 비활성화
GET /trips?driver_id=&status=	로그인	운행 목록 (기사: 본인만, 관리자: 같은 기업)
POST /trips	관리자	운행 생성
GET /trips/{id}	로그인	운행 상세
GET /trips/{id}/polyline	로그인	실제 도로 경로선 좌표
PATCH /trips/{id}/waypoints	관리자	경유지 추가 + 앱에 재경로 알림
PATCH /trips/{id}/status	로그인	운행 완료/취소 (?status=completed|cancelled)
POST /optimize	로그인	경로 최적화 (extra_stops, route_mode 지원)
POST /optimize/replan	로그인	운행 중 재경로
배송/위치
엔드포인트	권한	설명
POST /deliveries	관리자	배송지 단건 등록
POST /deliveries/batch	관리자	배송지 일괄 등록
PATCH /deliveries/{id}/assign	관리자	기사 배정
DELETE /deliveries/{id}	관리자	배송 취소
GET /deliveries	로그인	배송 목록
GET /deliveries/{id}	로그인	배송 상세
PATCH /deliveries/{id}/complete	기사	수동 완료
GET /address/coord?query=	없음	주소 → 좌표 변환
POST /rest-spots	없음	근처 휴식 장소 검색 (카카오 로컬)
POST /location-logs	로그인	GPS 수신 + 자동 완료 + WS broadcast (5초 주기)
GET /location-logs/{user_id}	관리자	기사 현재 위치 (Redis)
WS /ws/location	없음	실시간 위치 + 재경로 알림 WebSocket
주의사항
- 좌표: lon 사용 (lng 금지). rest_stops만 latitude/longitude 예외
- bcrypt==4.0.1 고정 (4.2+는 passlib 1.7.4 호환 문제)
- SQLAlchemy 비동기: db.query() 금지 → await db.execute(select())
- build_time_matrix() → (time_matrix, dist_matrix) 튜플 반환
- insert_rest_stops() → async, 반드시 await
- main.py 단일 파일 구조 유지 (추후 리팩토링 예정)
- 카카오 API Key 프론트엔드 하드코딩 금지 → /config 엔드포인트 경유
- Nginx: /api/* → FastAPI, /ws/* → WebSocket 프록시
- GPS 전송 주기: 5초 (앱 설정)
- 기업 등록 서류: backend/uploads/{org_id}/ 에 저장
- 슈퍼관리자 계정은 superadmin/create-account로 직접 생성
개발 로드맵
 FastAPI 백엔드 + Docker 5컨테이너
 PostgreSQL + TimescaleDB + Redis
 JWT 인증 + 회원가입/로그인
 배송 CRUD API
 GPS 수신 + 50m 자동 완료
 카카오맵/모빌리티 API 전환
 OR-Tools TSP + 휴게소 삽입 마이그레이션
 비동기(asyncio) 전환
 관리자 웹 (로그인, 대시보드, 카카오맵)
 PATCH /auth/me 회원 정보 수정
 lon/lng 통일
 졸음쉼터 시드 데이터 253건
 TTL 캐시 + find_best_rest_stop picker
 extra_stops / route_mode / dist_matrix
 WebSocket 실시간 위치
 GET /trips/{id}/polyline 경로선 API
 관리자 웹 실시간 경로선 표시
 PATCH /trips/{id}/waypoints 원격 배차
 PATCH /trips/{id}/status 운행 완료/취소
 앱 연동 확인
 다중 기업(organizations) 구조
 슈퍼 관리자 기업 심사 (승인/반려 + 이메일 알림)
 Oracle Cloud 서버 마이그레이션
 앱 WS replan_requested 수신 → 자동 replan (팀원 A)
 관리자 웹 운행 생성 UI
 발표 준비
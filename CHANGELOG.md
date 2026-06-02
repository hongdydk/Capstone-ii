# Changelog

이 문서는 저장소의 Git 커밋 이력을 누락 없이 정리한 기록입니다.
정렬 기준은 날짜 오름차순(전체 이력)이며, 최근 주요 변경은 최신순으로 제공합니다.

## 요약

- 2026-06-02에 데이터 샘플/스크립트 추가와 관제 UX 개편이 집중 반영되었습니다.
- `feat` 커밋으로 다차량 배차 계약(VRPTW/휴게 삽입 포함)과 목업 구조 이전이 진행되었습니다.
- `docs` 커밋으로 README/PLAN/CHANGELOG와 API 계약 문서 동기화가 이뤄졌습니다.
- 2026-05-03 전후로 GraphHopper 연동 및 Kakao API 제거 등 라우팅 엔진 축이 정리되었습니다.
- 2026-04월에는 휴게소 검색/삽입, 시간·거리 행렬, 테스트 분리 등 최적화 기초 작업이 축적되었습니다.
- 최초 커밋(2026-03-13)부터 현재(2026-06-02)까지 전체 이력을 유지합니다.

## 최근 주요 변경

- 2026-06-02 · 6ad2c5c · [feat] · feat: 관제 목업 UX 개편 및 라이트 테마 변형 추가 (hongdydk)
- 2026-06-02 · d431c4b · [docs] · docs: README·CHANGELOG·PLAN 배차·데이터·API 계약 동기화 (hongdydk)
- 2026-06-02 · 1ee44bf · [feat] · feat: 관제·내비 목업을 frontend_Test로 이전 (control TOC·앱 mockup)
  (hongdydk)
- 2026-06-02 · a2140e7 · [feat] · feat: 다차량 출발·시간창·배차 계약 강화 및 VRPTW·휴게 삽입 테스트
  (hongdydk)
- 2026-06-02 · 62930a9 · [data] · data: 가짜 물류 주문·정차 CSV 및 태스크 양식 xlsx 샘플 (hongdydk)
- 2026-06-02 · 8a784c9 · [chore] · scripts: OD 통계·가짜 물류 데이터·태스크 xlsx 생성 스크립트
  (hongdydk)
- 2026-06-02 · 42ee3ed · [data] · data: OD 화물통계 표22-26 참조 JSON 및 data README 추가 (hongdydk)
- 2026-05-27 · d5b6f1d · [docs] · docs: 웹·앱 API 계약·배차 플랜·사후 통계 토론안 및 Cursor 팀 에이전트
  (hongdydk)
- 2026-05-13 · 94a971f · [feat] · feat: VRPTW 다차량 배차 구현 및 cargo 상하차 스키마 개편 (hongdydk)
- 2026-05-03 · 77d1322 · [chore] · 변경 (hongdydk)

## 전체 커밋 이력

- 2026-03-13 · d3f7435 · [chore] · first commit (hongdydk)
- 2026-03-13 · 5aaf018 · [chore] · main (hongdydk)
- 2026-03-13 · ab92df3 · [chore] · Revert "main" (hongdydk)
- 2026-03-15 · ed8f0ca · [docs] · README UPDATE (hongdydk)
- 2026-03-25 · bf20074 · [chore] · KDU_RouteOn First Commit (hongdydk)
- 2026-03-25 · 60e124a · [chore] · Delete (hongdydk)
- 2026-03-27 · 08f987a · [data] · 상하행 데이터 추가 (hongdydk)
- 2026-03-31 · 0c1b503 · [fix] · 카키오 api 변경 후 재작업 (hongdydk)
- 2026-04-01 · bce0c4a · [feat] · 예제 api 코드 추가 (hongdydk)
- 2026-04-01 · 27628a5 · [fix] · 버그수정및 다중 목적지 이용한 지역내 루트 최적화 (hongdydk)
- 2026-04-01 · 733dd18 · [fix] · 공영차고지 부분은 휴식장소 검색시 제거 (hongdydk)
- 2026-04-01 · 9d81ea2 · [feat] · 검색 캐시 적용(1시간) 휴게소 선택 다중목적지 api로 검색 (hongdydk)
- 2026-04-01 · c6abf48 · [test] · 시간 행렬에서 시간거리 행렬로 변경 및 테스트 추가 api 작동 확인 완료
  (hongdydk)
- 2026-04-01 · 3ed6863 · [test] · 테스트 분리 (hongdydk)
- 2026-04-01 · bbe9298 · [test] · 지역내 루트파인딩 휴게장소 찾기+ 차량 타입 추가+ 버그 추가+ 테스트추가
  (hongdydk)
- 2026-04-01 · 059da26 · [feat] · 거리 비례로 루트 파인딩 변경 (hongdydk)
- 2026-04-04 · ce883bc · [fix] · 수정 완료 (hongdydk)
- 2026-04-04 · 78aa91f · [fix] · 병합 오류 해결 (hongdydk)
- 2026-04-08 · f763dba · [fix] · 오류 해결 (hongdydk)
- 2026-04-15 · 1cbf0e4 · [chore] · 필요없는거 제거 (hongdydk)
- 2026-04-15 · 3e8df32 · [fix] · 고속도로 적용 오류 제거후 고속도로 api로 변경 (hongdydk)
- 2026-04-29 · 9730733 · [feat] · 쉼터 방법 변경 (hongdydk)
- 2026-04-29 · 9a75718 · [feat] · 시간적 제약 추가 (hongdydk)
- 2026-05-02 · 9eaef5e · [feat] · 상차 id 하차 id 동일화 (hongdydk)
- 2026-05-03 · ff92fdb · [feat] · GraphHopper 라우팅 엔진 연동 및 휴게소 삽입 로직 개선 (hongdydk)
- 2026-05-03 · 03fec5e · [docs] · readme, 적용방법 업데이트 테스트중 문제 생긴거 고침 (hongdydk)
- 2026-05-03 · 635b670 · [feat] · 재미로 만든 웹 내비게이션 (hongdydk)
- 2026-05-03 · 2d9455f · [chore] · 쓸데 없는거 변경 (hongdydk)
- 2026-05-03 · 4b1fe1e · [chore] · 카카오 api 제거 (hongdydk)
- 2026-05-03 · 605aba7 · [chore] · 그래프호퍼 버전 변경 (hongdydk)
- 2026-05-03 · 0c93565 · [chore] · 작업용 파일 변경 (hongdydk)
- 2026-05-03 · 77d1322 · [chore] · 변경 (hongdydk)
- 2026-05-13 · 94a971f · [feat] · feat: VRPTW 다차량 배차 구현 및 cargo 상하차 스키마 개편 (hongdydk)
- 2026-05-27 · d5b6f1d · [docs] · docs: 웹·앱 API 계약·배차 플랜·사후 통계 토론안 및 Cursor 팀 에이전트
  (hongdydk)
- 2026-06-02 · 42ee3ed · [data] · data: OD 화물통계 표22-26 참조 JSON 및 data README 추가 (hongdydk)
- 2026-06-02 · 8a784c9 · [chore] · scripts: OD 통계·가짜 물류 데이터·태스크 xlsx 생성 스크립트
  (hongdydk)
- 2026-06-02 · 62930a9 · [data] · data: 가짜 물류 주문·정차 CSV 및 태스크 양식 xlsx 샘플 (hongdydk)
- 2026-06-02 · a2140e7 · [feat] · feat: 다차량 출발·시간창·배차 계약 강화 및 VRPTW·휴게 삽입 테스트
  (hongdydk)
- 2026-06-02 · 1ee44bf · [feat] · feat: 관제·내비 목업을 frontend_Test로 이전 (control TOC·앱 mockup)
  (hongdydk)
- 2026-06-02 · d431c4b · [docs] · docs: README·CHANGELOG·PLAN 배차·데이터·API 계약 동기화 (hongdydk)
- 2026-06-02 · 6ad2c5c · [feat] · feat: 관제 목업 UX 개편 및 라이트 테마 변형 추가 (hongdydk)

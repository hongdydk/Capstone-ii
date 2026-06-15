# Changelog

??문서???�?�소??Git 커밋 ?�력???�락 ?�이 ?�리??기록?�니??
?�렬 기�??� ?�짜 ?�름차순(?�체 ?�력)?�며, 최근 주요 변경�? 최신?�으�??�공?�니??

**커밋 관례:** 기능·?�정�?`CHANGELOG` 갱신(?�약·?�최�?주요 변경�??� **??커밋??* ?�함?�니??
백엔?�·이???��? 변�???`BUGREPORT.md` ?�당 ??�� `?�태` 줄도 **같�? 커밋??* 갱신?�니??CHANGELOG-only·BUGREPORT-only 2번째 커밋 금�?).
`CHANGELOG???�시 반영` ?�용 follow-up 커밋?� ?��? ?�습?�다. ?�전�?커밋 ?�력???�시???�시 ???�는 ?�음 커밋 ??맞춰???�니??

## ?�약

- 2026-06-14 **H3-D** ?�책 ?�정 ??optimize 7200�?초과�??�전 ?�게·6000 replan ?�리거·�?.4 ?�행 검�?MVP 범위; A 기각 ([BUGREPORT H3](BUGREPORT.md#h3--optimize-7200--replan-6000--?�게-?�입?�행-검�??�책), ARCHITECTURE §3.4, PLAN §3.4.3) (docs only, 미커�?.
- 2026-06-14??[ARCHITECTURE.md §3.4 ?�행 검�?(ARCHITECTURE.md#34-?�행-검�?replan-?? 추�? ??optimize 7200/replan 6000 ?�책·MVP·권장·TBD ?�어, H3·M3·PLAN·SCHEMA cross-ref (docs only, 미커�?.
- 2026-06-14??Phase 2 `prepare_replan_nodes`·`run_with_rest_core`�?with_rest·replan TSP 블록 ?�합 �?ARCHITECTURE·PLAN·SCHEMA·README ?�기??
- 2026-06-14??`ARCHITECTURE.md` ?�설(백엔???�이?�·파?�프?�인·?�태·GH ?�책·리팩??로드�? �?Phase 1 `apply_route_to_trip` ?�일 persist ?�합(`0ff3435`).
- 2026-06-12??H2-A(with_rest·replan polyline GH ?�패 ??503 fail-fast, `polyline=[]` ?�백 ?�거) 구현 ??BUGREPORT 백로그에???�거(15�??��?, ?�력?� �?문서·커밋?�만).
- 2026-06-11??H1(GH ?�렬 503 fail-fast)·H4(replan `optimized_route`·`route_version`) 구현 ?�료(eb7bd91) ??BUGREPORT 백로그에???�거(16�??��?, ?�력?� �?문서·커밋?�만).
- 2026-06-11??BUGREPORT·CHANGELOG ?�일 커밋 규칙, subagentStop Hook(마�?�?커밋 ?�후 변�?규모·?�슈 ?�트), ?�택??.githooks pre-commit·scripts/check_bugreport_sync.py�??�리.
- 2026-06-11??optimize 2?�계: `route_pipeline` 모듈 분리, `POST /optimize/basic`·`/optimize/with-rest` ?�용 ?�드?�인??추�? (`POST /optimize/`??`optimize_mode` ?�임 ?��?).
- 2026-06-11??`POST /optimize/`??optional `optimize_mode` (`basic` \| `with_rest`, 기본 `with_rest`) 추�? ??basic?� ?�청 ?�서 고정·?�게 ?�입 ?�략, replan?� with_rest ?��?.
- 2026-06-11??`BUGREPORT.md` ?�설(?�영·?�고리즘 ?�슈 H1?�H4·M1?�M8·L1?�L6, P0?�P3)·`PLAN.md` §8 ?�약·링크 ?�리 �?README 문서 �?반영.
- 2026-06-11??`DEPLOY.md` ?�거(OCI Docker 배포 ?�료)·`PLAN.md` §8 ?�영 ?�정?�·알고리�?백로�?H1?�H4, M1?�M8, L1?�L6) 추�? �?README 문서 �??�리.
- 2026-06-10??GH `instructions` 기반 경로 ?�간·거리 ?�로?�일�?법정 ?�게 ?�입 ?��??��? 개선(P0: `graphhopper`·`rest_stop_inserter`·`optimize`/`demo` ?�동)?�고, subagentStop 커밋 ?�안 Hook·`commit-prompt` ?�킬·?�이?�트(문서??관�??�거·?��??�어·리뷰??보강) �?**?�일 커밋+CHANGELOG ?�시** 관례�??�리?�습?�다.
- 2026-06-10??`PLAN.md` ?�면 ?�작??지?�기??�?배차?�·자�??�비·OSM 지?�·내�??�료 계약·?�시�?교통·공공 API ?�선?�위)�?README·SCHEMA·?� ??�� 규칙 ?�렬, `frontend_Test` ?�적 목업 ?�거·?�차??dispatch API ?�리·Kakao 지?�코???�용 축소가 반영?�었?�니??
- `frontend_Test` ?�거 ??README·`PLAN.md`·`.cursor/rules/team-roles.mdc`??경로 참조�?관???�·앱 ?�?�소 `[TBD]` ?�기�??�리?�고, 문서??관�??�이?�트??커밋·?�시 ??`CHANGELOG.md` ?�기??지침을 추�??�습?�다.
- 2026-06-02???�이???�플/?�크립트 추�??� 관??UX 개편??집중 반영?�었?�니??
- `feat` 커밋?�로 ?�차??배차 계약(VRPTW/?�게 ?�입 ?�함)�?목업 구조 ?�전??진행?�었?�니??
- `docs` 커밋?�로 README/PLAN/CHANGELOG?� API 계약 문서 ?�기?��? ?�뤄졌습?�다.
- 2026-05-03 ?�후�?GraphHopper ?�동 �?Kakao API ?�거 ???�우???�진 축이 ?�리?�었?�니??
- 2026-04?�에???�게??검???�입, ?�간·거리 ?�렬, ?�스??분리 ??최적??기초 ?�업??축적?�었?�니??
- 최초 커밋(2026-03-13)부???�재(2026-06-10)까�? ?�체 ?�력???��??�니??

## 최근 주요 변�?

- 2026-06-14 · [refactor] · refactor: Phase 2 `prepare_replan_nodes`·`run_with_rest_core`�?with_rest·replan TSP 블록 ?�합
- 2026-06-14 · [refactor] · refactor: Phase 1 `apply_route_to_trip` ?�일 persist (`0ff3435`)
- 2026-06-12 · [fix] · fix: with_rest·replan polyline GH ?�패 503 fail-fast(H2-A), ?�게 ?�이 200 반환 금�?
- 2026-06-11 · [chore] · chore: BUGREPORT ?�기??commit-prompt·Hook·pre-commit 경고·check ?�크립트), H1·H4 백로�??�거·PLAN 16�?(hongdydk)
- 2026-06-11 · [feat] · feat: `POST /optimize/` `optimize_mode` basic/with_rest (기본 with_rest, replan unchanged) (hongdydk)
- 2026-06-11 · [fix] · fix: GH ?�렬 ?�패 503 fail-fast(H1)·replan `optimized_route` DB 갱신·`route_version`(H4) (hongdydk)
- 2026-06-11 · [docs] · docs: BUGREPORT.md ?�영·?�고리즘 백로�??�설 �?PLAN §8·README 문서 �??�리 (hongdydk)
- 2026-06-11 · [docs] · docs: DEPLOY.md ?�거 �?PLAN ?�영·?�고리즘 백로�?§8 추�? (hongdydk)
- 2026-06-10 · [feat] · feat: ?�게 ?�입 GH instructions ?�로?�일(P0) �?subagentStop 커밋 ?�안 Hook (hongdydk)
- 2026-06-10 · 6863990 · [docs] · docs: frontend_Test ?�거 ??문서 참조 ?�리 �?CHANGELOG·문서??지�?(hongdydk)
- 2026-06-10 · d46610c · [chore] · chore: frontend_Test 목업 ?�거 �?dispatch API·Kakao ?�우???�리 (hongdydk)
- 2026-06-10 · a104696 · [docs] · docs: PLAN �?배차·?�체 ?�비·OSM �??�면 ?�리 �?README·SCHEMA·?� ??�� ?�렬 (hongdydk)
- 2026-06-02 · 3694dd3 · [docs] · docs: 문서 체계 ?�폐??�?changelog 복원/가?�성 개선 (hongdydk)
- 2026-06-02 · 6ad2c5c · [feat] · feat: 관??목업 UX 개편 �??�이???�마 변??추�? (hongdydk)
- 2026-06-02 · d431c4b · [docs] · docs: README·CHANGELOG·PLAN 배차·?�이?�·API 계약 ?�기??(hongdydk)
- 2026-06-02 · 1ee44bf · [feat] · feat: 관?�·내�?목업??frontend_Test�??�전 (control TOC·??mockup)
  (hongdydk)
- 2026-06-02 · a2140e7 · [feat] · feat: ?�차??출발·?�간창·배�?계약 강화 �?VRPTW·?�게 ?�입 ?�스??
  (hongdydk)
- 2026-06-02 · 62930a9 · [data] · data: 가�?물류 주문·?�차 CSV �??�스???�식 xlsx ?�플 (hongdydk)
- 2026-06-02 · 8a784c9 · [chore] · scripts: OD ?�계·가�?물류 ?�이?�·태?�크 xlsx ?�성 ?�크립트
  (hongdydk)
- 2026-06-02 · 42ee3ed · [data] · data: OD ?�물?�계 ??2-26 참조 JSON �?data README 추�? (hongdydk)
- 2026-05-27 · d5b6f1d · [docs] · docs: ?�·앱 API 계약·배차 ?�랜·?�후 ?�계 ?�론??�?Cursor ?� ?�이?�트
  (hongdydk)
- 2026-05-13 · 94a971f · [feat] · feat: VRPTW ?�차??배차 구현 �?cargo ?�하�??�키�?개편 (hongdydk)
- 2026-05-03 · 77d1322 · [chore] · 변�?(hongdydk)

## ?�체 커밋 ?�력

- 2026-03-13 · d3f7435 · [chore] · first commit (hongdydk)
- 2026-03-13 · 5aaf018 · [chore] · main (hongdydk)
- 2026-03-13 · ab92df3 · [chore] · Revert "main" (hongdydk)
- 2026-03-15 · ed8f0ca · [docs] · README UPDATE (hongdydk)
- 2026-03-25 · bf20074 · [chore] · KDU_RouteOn First Commit (hongdydk)
- 2026-03-25 · 60e124a · [chore] · Delete (hongdydk)
- 2026-03-27 · 08f987a · [data] · ?�하???�이??추�? (hongdydk)
- 2026-03-31 · 0c1b503 · [fix] · 카키??api 변�????�작??(hongdydk)
- 2026-04-01 · bce0c4a · [feat] · ?�제 api 코드 추�? (hongdydk)
- 2026-04-01 · 27628a5 · [fix] · 버그?�정�??�중 목적지 ?�용??지??�� 루트 최적??(hongdydk)
- 2026-04-01 · 733dd18 · [fix] · 공영차고지 부분�? ?�식?�소 검?�시 ?�거 (hongdydk)
- 2026-04-01 · 9d81ea2 · [feat] · 검??캐시 ?�용(1?�간) ?�게???�택 ?�중목적지 api�?검??(hongdydk)
- 2026-04-01 · c6abf48 · [test] · ?�간 ?�렬?�서 ?�간거리 ?�렬�?변�?�??�스??추�? api ?�동 ?�인 ?�료
  (hongdydk)
- 2026-04-01 · 3ed6863 · [test] · ?�스??분리 (hongdydk)
- 2026-04-01 · bbe9298 · [test] · 지??�� 루트?�인???�게?�소 찾기+ 차량 ?�??추�?+ 버그 추�?+ ?�스?�추가
  (hongdydk)
- 2026-04-01 · 059da26 · [feat] · 거리 비�?�?루트 ?�인??변�?(hongdydk)
- 2026-04-04 · ce883bc · [fix] · ?�정 ?�료 (hongdydk)
- 2026-04-04 · 78aa91f · [fix] · 병합 ?�류 ?�결 (hongdydk)
- 2026-04-08 · f763dba · [fix] · ?�류 ?�결 (hongdydk)
- 2026-04-15 · 1cbf0e4 · [chore] · ?�요?�는�??�거 (hongdydk)
- 2026-04-15 · 3e8df32 · [fix] · 고속?�로 ?�용 ?�류 ?�거??고속?�로 api�?변�?(hongdydk)
- 2026-04-29 · 9730733 · [feat] · ?�터 방법 변�?(hongdydk)
- 2026-04-29 · 9a75718 · [feat] · ?�간???�약 추�? (hongdydk)
- 2026-05-02 · 9eaef5e · [feat] · ?�차 id ?�차 id ?�일??(hongdydk)
- 2026-05-03 · ff92fdb · [feat] · GraphHopper ?�우???�진 ?�동 �??�게???�입 로직 개선 (hongdydk)
- 2026-05-03 · 03fec5e · [docs] · readme, ?�용방법 ?�데?�트 ?�스?�중 문제 ?�긴�?고침 (hongdydk)
- 2026-05-03 · 635b670 · [feat] · ?��?�?만든 ???�비게이??(hongdydk)
- 2026-05-03 · 2d9455f · [chore] · ?�데 ?�는�?변�?(hongdydk)
- 2026-05-03 · 4b1fe1e · [chore] · 카카??api ?�거 (hongdydk)
- 2026-05-03 · 605aba7 · [chore] · 그래?�호??버전 변�?(hongdydk)
- 2026-05-03 · 0c93565 · [chore] · ?�업???�일 변�?(hongdydk)
- 2026-05-03 · 77d1322 · [chore] · 변�?(hongdydk)
- 2026-05-13 · 94a971f · [feat] · feat: VRPTW ?�차??배차 구현 �?cargo ?�하�??�키�?개편 (hongdydk)
- 2026-05-27 · d5b6f1d · [docs] · docs: ?�·앱 API 계약·배차 ?�랜·?�후 ?�계 ?�론??�?Cursor ?� ?�이?�트
  (hongdydk)
- 2026-06-02 · 42ee3ed · [data] · data: OD ?�물?�계 ??2-26 참조 JSON �?data README 추�? (hongdydk)
- 2026-06-02 · 8a784c9 · [chore] · scripts: OD ?�계·가�?물류 ?�이?�·태?�크 xlsx ?�성 ?�크립트
  (hongdydk)
- 2026-06-02 · 62930a9 · [data] · data: 가�?물류 주문·?�차 CSV �??�스???�식 xlsx ?�플 (hongdydk)
- 2026-06-02 · a2140e7 · [feat] · feat: ?�차??출발·?�간창·배�?계약 강화 �?VRPTW·?�게 ?�입 ?�스??
  (hongdydk)
- 2026-06-02 · 1ee44bf · [feat] · feat: 관?�·내�?목업??frontend_Test�??�전 (control TOC·??mockup)
  (hongdydk)
- 2026-06-02 · d431c4b · [docs] · docs: README·CHANGELOG·PLAN 배차·?�이?�·API 계약 ?�기??(hongdydk)
- 2026-06-02 · 3694dd3 · [docs] · docs: 문서 체계 ?�폐??�?changelog 복원/가?�성 개선 (hongdydk)
- 2026-06-02 · 6ad2c5c · [feat] · feat: 관??목업 UX 개편 �??�이???�마 변??추�? (hongdydk)
- 2026-06-10 · d46610c · [chore] · chore: frontend_Test 목업 ?�거 �?dispatch API·Kakao ?�우???�리 (hongdydk)
- 2026-06-10 · a104696 · [docs] · docs: PLAN �?배차·?�체 ?�비·OSM �??�면 ?�리 �?README·SCHEMA·?� ??�� ?�렬 (hongdydk)
- 2026-06-10 · 6863990 · [docs] · docs: frontend_Test ?�거 ??문서 참조 ?�리 �?CHANGELOG·문서??지�?(hongdydk)
- 2026-06-10 · [feat] · feat: ?�게 ?�입 GH instructions ?�로?�일(P0) �?subagentStop 커밋 ?�안 Hook (hongdydk)

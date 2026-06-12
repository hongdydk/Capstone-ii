---
name: commit-prompt
description: >-
  subagentStop Hook이 커밋 followup을 넣었을 때의 규칙. 사용자가 명시적으로 승인하기 전에는
  커밋·푸시하지 않는다. 코딩 작업 완료 시 변경 요약을 채팅에 직접 보여 준다.
  한 작업 단위는 소스와 CHANGELOG·(해당 시) BUGREPORT를 같은 커밋 1회에 포함한다.
---

# Commit Prompt (Hook follow-up)

`subagentStop` Hook이 `followup_message`로 커밋을 **제안**한 경우:

1. **승인 전 커밋 금지** — 사용자가 "커밋해", "예", "푸시해" 등으로 명시할 때까지 `git commit`·`git push`를 실행하지 않는다.
2. **승인 후** — `repo-ship` 스킬 지침을 따른다: 관련 파일 stage, `CHANGELOG.md` 갱신, 백엔드·이슈 연관 변경 시 `BUGREPORT.md` 해당 항목 `상태` 줄 갱신, 1–2문장 커밋 메시지.
3. Hook 제안만으로는 CHANGELOG를 선제 수정하지 않는다.

## 단일 커밋 원칙 (필수)

- **한 작업 단위 = `git commit` 1회**
- **같은 커밋에 포함:** 소스·설정·테스트 변경 + `CHANGELOG.md` (「요약」·「최근 주요 변경」)
- **같은 커밋에 포함 (해당 시):** `BUGREPORT.md` — 구현·결정 반영 시 해당 항목 `**상태:**` 줄 갱신 (`[x] 구현완료` 등). CHANGELOG 요약과 함께 유지.
- **금지:** `docs: CHANGELOG에 해시 반영`·`docs: BUGREPORT 상태 갱신` 등 문서-only **2번째 커밋**
- **「전체 커밋 이력」 해시**
  - 푸시 후 또는 **다음 커밋 시** 갱신해도 됨
  - 같은 커밋에 넣을 때: stage 후 커밋 → `git log -1`로 해시 확인 → CHANGELOG 이력 줄 갱신 → `git commit --amend --no-edit` (여전히 커밋 1개)
  - 또는 이력 줄은 **해시 없이 요약만** 기록해도 됨

## 작업 완료 시 변경 요약 (Hook 없이도)

코딩·리팩터 등 **저장소를 바꾸는 작업을 마쳤을 때**, Hook follow-up 여부와 관계없이 응답 말미에 **현재 워킹 트리 요약**을 채팅에 직접 포함한다.

1. `git log -1 --oneline`으로 **기준 커밋**(HEAD)을 확인한다.
2. `git status -sb`와 `git diff --stat`(필요 시 `git diff --cached --stat`)를 실행한다.
3. 요약은 **코드·설정 파일만** 집계한다 — `*.md`(CHANGELOG, BUGREPORT, PLAN 등)는 파일 목록·줄 수(+/-)에서 **제외**한다. (`git diff --stat` 전체를 그대로 붙이지 말고, md 경로는 필터링하거나 별도 집계하지 않는다.)
4. 결과를 아래 **표 형식**으로 정리한다 — 요약 표 + 변경 경로 bullet. 파일이 10개를 넘으면 상위 10개 bullet + `… 외 N개`. **md만** 변경된 경우 followup·요약 블록은 생략한다.

   ```
   📋 **마지막 커밋 이후 변경** (`d2aa6ed`, md 제외)

   | | |
   |---|---|
   | **파일** | 2 |
   | **줄** | +110 / −20 |

   - `backend/app/services/route_pipeline.py`
   - `backend/tests/test_optimize_mode.py`
   ```

   (파일별 줄 수가 필요하면 `| 파일 | 변경 |` 표를 쓸 수 있음 — 예: `route_pipeline.py` | +50/−20. Hook `commit_prompt_on_stop.py`와 동일 규칙.)
5. **금지:** `커밋·푸시가 필요하면 알려 주세요` 등 사용자에게 커밋을 **요청하라고** 말하지 않는다. 규모만 사실로 보고한다.
6. (선택) Source Control(`Ctrl+Shift+G`)·Review 안내는 diff가 있을 때만 한 줄.

Hook follow-up·작업 완료 응답 모두 위 형식을 따른다. 사용자가 명시적으로 커밋·푸시를 요청할 때만 `repo-ship`으로 진행한다. 승인 시 **커밋 1회**에 CHANGELOG·(해당 시) BUGREPORT를 함께 포함한다.

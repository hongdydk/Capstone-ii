---
name: commit-prompt
description: >-
  subagentStop Hook이 커밋 followup을 넣었을 때의 규칙. 사용자가 명시적으로 승인하기 전에는
  커밋·푸시하지 않는다. 코딩 작업 완료 시 변경 요약을 채팅에 직접 보여 준다.
  한 작업 단위는 소스와 CHANGELOG를 같은 커밋 1회에 포함한다.
---

# Commit Prompt (Hook follow-up)

`subagentStop` Hook이 `followup_message`로 커밋을 **제안**한 경우:

1. **승인 전 커밋 금지** — 사용자가 "커밋해", "예", "푸시해" 등으로 명시할 때까지 `git commit`·`git push`를 실행하지 않는다.
2. **승인 후** — `repo-ship` 스킬 지침을 따른다: 관련 파일 stage, `CHANGELOG.md` 갱신, 1–2문장 커밋 메시지.
3. Hook 제안만으로는 CHANGELOG를 선제 수정하지 않는다.

## 단일 커밋 원칙 (필수)

- **한 작업 단위 = `git commit` 1회**
- **같은 커밋에 포함:** 소스·설정·테스트 변경 + `CHANGELOG.md` (「요약」·「최근 주요 변경」)
- **금지:** `docs: CHANGELOG에 해시 반영` 등 CHANGELOG-only **2번째 커밋**
- **「전체 커밋 이력」 해시**
  - 푸시 후 또는 **다음 커밋 시** 갱신해도 됨
  - 같은 커밋에 넣을 때: stage 후 커밋 → `git log -1`로 해시 확인 → CHANGELOG 이력 줄 갱신 → `git commit --amend --no-edit` (여전히 커밋 1개)
  - 또는 이력 줄은 **해시 없이 요약만** 기록해도 됨

## 작업 완료 시 변경 요약 (Hook 없이도)

코딩·리팩터 등 **저장소를 바꾸는 작업을 마쳤을 때**, Hook follow-up 여부와 관계없이 응답 말미에 **현재 워킹 트리 요약**을 채팅에 직접 포함한다.

1. `git status -sb`와 `git diff --stat`(필요 시 `git diff --cached --stat`)를 실행한다.
2. 결과를 읽기 쉬운 한국어 블록으로 정리한다 — 예: `📋 워킹 트리 변경 요약`, 파일별 `M`/`A`/`D`·경로·`+/-` 줄 수.
3. Cursor UI 안내를 **한 줄** 덧붙인다: **Source Control**(`Ctrl+Shift+G`)에서 파일별 diff 확인, 채팅 하단 **Review** 버튼으로 변경 검토.

커밋을 제안할 때만 위 요약 뒤에 커밋·CHANGELOG·푸시 문구를 붙인다. 승인 전에는 커밋하지 않는다. 승인 시 **커밋 1회**에 CHANGELOG를 함께 포함한다.

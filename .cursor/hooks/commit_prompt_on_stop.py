#!/usr/bin/env python3
"""subagentStop hook: summarize git changes and suggest a commit follow-up."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

EXCLUDE_PATTERNS = (
    re.compile(r"(^|/)__pycache__(/|$)"),
    re.compile(r"(^|/)\.pytest_cache(/|$)"),
    re.compile(r"\.pyc$"),
    re.compile(r"(^|/)\.env$"),
)

IMPORTANT_UNTRACKED_PREFIXES = (
    "backend/",
    "Engine/",
    "PLAN",
    "SCHEMA",
    "CHANGELOG",
    "BUGREPORT",
)

# Path fragment → BUGREPORT issue ID hints (for follow-up messages).
PATH_ISSUE_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"graphhopper\.py"), "H1"),
    (re.compile(r"rest_stop_inserter"), "H2/H3"),
    (re.compile(r"route_pipeline|replan"), "H4"),
    (re.compile(r"optimize\.py"), "H1/H4"),
    (re.compile(r"config\.py"), "L2"),
)

BUG_BACKEND_PREFIXES = ("backend/", "Engine/")

MIN_LINE_DELTA = 20
MIN_FILE_COUNT = 2


def _is_excluded(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(p.search(normalized) for p in EXCLUDE_PATTERNS)


def _emit_json(payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


def _run_git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _parse_porcelain(status_output: str) -> tuple[list[tuple[str, str]], int]:
    """Return (status_code, path) pairs and count of excluded entries."""
    entries: list[tuple[str, str]] = []
    excluded_count = 0
    for line in status_output.splitlines():
        if not line.strip():
            continue
        code = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if _is_excluded(path):
            excluded_count += 1
            continue
        entries.append((code, path.replace("\\", "/")))
    return entries, excluded_count


def _parse_numstat(numstat_output: str) -> dict[str, tuple[int, int]]:
    stats: dict[str, tuple[int, int]] = {}
    for line in numstat_output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        add_s, del_s, path = parts
        if _is_excluded(path):
            continue
        try:
            added = int(add_s) if add_s != "-" else 0
            deleted = int(del_s) if del_s != "-" else 0
        except ValueError:
            continue
        normalized = path.replace("\\", "/")
        prev = stats.get(normalized, (0, 0))
        stats[normalized] = (prev[0] + added, prev[1] + deleted)
    return stats


def _merge_numstat(*parts: dict[str, tuple[int, int]]) -> dict[str, tuple[int, int]]:
    merged: dict[str, tuple[int, int]] = {}
    for part in parts:
        for path, (added, deleted) in part.items():
            prev = merged.get(path, (0, 0))
            merged[path] = (prev[0] + added, prev[1] + deleted)
    return merged


def _status_label(code: str) -> str:
    if "D" in code:
        return "D"
    if "?" in code:
        return "A"
    if "A" in code:
        return "A"
    if any(ch in code for ch in "MRCU"):
        return "M"
    stripped = code.strip()
    return stripped if stripped else "?"


def _format_delta(code: str, path: str, numstat: dict[str, tuple[int, int]]) -> str:
    added, deleted = numstat.get(path, (0, 0))
    if "?" in code and (added, deleted) == (0, 0):
        return " (신규)"
    if added or deleted:
        return f" (+{added}/-{deleted})"
    if "D" in code:
        return " (삭제)"
    return ""


def _format_file_list(
    entries: list[tuple[str, str]],
    numstat: dict[str, tuple[int, int]],
) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for code, path in sorted(entries, key=lambda item: item[1]):
        if path in seen:
            continue
        seen.add(path)
        label = _status_label(code)
        delta = _format_delta(code, path, numstat)
        lines.append(f"  {label}  {path}{delta}")
    return lines


def _has_important_untracked(entries: list[tuple[str, str]]) -> bool:
    for code, path in entries:
        if "?" not in code:
            continue
        for prefix in IMPORTANT_UNTRACKED_PREFIXES:
            if path.startswith(prefix) or path == prefix.rstrip("/"):
                return True
    return False


def _only_cursor_agents(entries: list[tuple[str, str]]) -> bool:
    if not entries:
        return False
    return all(
        path.startswith(".cursor/agents/") or path == ".cursor/agents"
        for _, path in entries
    )


def _is_bugreport_path(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return base.upper() == "BUGREPORT.MD"


def _has_backend_issue_changes(entries: list[tuple[str, str]]) -> bool:
    for _, path in entries:
        if path.startswith(BUG_BACKEND_PREFIXES):
            return True
        for pattern, _ in PATH_ISSUE_HINTS:
            if pattern.search(path):
                return True
    return False


def _bugreport_modified(
    entries: list[tuple[str, str]],
    numstat: dict[str, tuple[int, int]],
) -> bool:
    for code, path in entries:
        if not _is_bugreport_path(path):
            continue
        added, deleted = numstat.get(path, (0, 0))
        if added or deleted or "?" in code:
            return True
    return False


def _bugreport_issue_hints(paths: list[str]) -> list[str]:
    hints: list[str] = []
    for path in paths:
        basename = path.rsplit("/", 1)[-1]
        for pattern, issue_id in PATH_ISSUE_HINTS:
            if pattern.search(path):
                hints.append(f"{basename}→{issue_id}")
                break
    return sorted(set(hints))


def _summarize_paths(paths: list[str], limit: int = 5) -> str:
    if not paths:
        return "(경로 없음)"
    head = paths[:limit]
    suffix = f" 외 {len(paths) - limit}개" if len(paths) > limit else ""
    return ", ".join(head) + suffix


def _should_prompt(
    entries: list[tuple[str, str]],
    total_added: int,
    total_deleted: int,
) -> bool:
    if not entries:
        return False
    if _has_important_untracked(entries):
        return True
    line_delta = total_added + total_deleted
    if len(entries) >= MIN_FILE_COUNT:
        return True
    if len(entries) >= 1 and line_delta >= MIN_LINE_DELTA:
        return True
    return False


def _build_followup(
    entries: list[tuple[str, str]],
    total_added: int,
    total_deleted: int,
    numstat: dict[str, tuple[int, int]],
    excluded_count: int,
    *,
    head_commit: str | None = None,
) -> str:
    paths = sorted({path for _, path in entries})
    top_by_delta = sorted(
        paths,
        key=lambda p: sum(numstat.get(p, (0, 0))),
        reverse=True,
    )
    file_lines = _format_file_list(entries, numstat)

    head_line = f"기준: {head_commit}" if head_commit else "기준: HEAD"
    lines = [
        f"📋 마지막 커밋 이후 변경 ({head_line})",
        "",
        *file_lines,
    ]

    if excluded_count:
        lines.append("")
        lines.append(f"  (제외됨 {excluded_count}개: __pycache__, .pyc 등)")

    lines.extend(
        [
            "",
            "서브에이전트 작업 후 저장소에 변경이 있습니다.",
            f"- 파일 {len(paths)}개, +{total_added}/-{total_deleted}줄",
            f"- 주요 경로: {_summarize_paths(top_by_delta)}",
        ]
    )

    if _only_cursor_agents(entries):
        lines.append("- 에이전트 설정만 변경됨")

    backend_issue = _has_backend_issue_changes(entries)
    if backend_issue:
        issue_hints = _bugreport_issue_hints(paths)
        if issue_hints:
            lines.append(f"- 관련 이슈 힌트: {', '.join(issue_hints)}")
        if not _bugreport_modified(entries, numstat):
            lines.append(
                "- BUGREPORT 상태 줄 확인: 백엔드 변경이 있으나 BUGREPORT.md 미수정"
            )

    lines.append(
        f"미커밋 — 파일 {len(paths)}개, +{total_added}/-{total_deleted}줄 "
        f"(커밋 시 CHANGELOG·해당 시 BUGREPORT 동일 커밋 1회)"
    )
    return "\n".join(lines)


def main() -> int:
    try:
        raw = sys.stdin.read()
        if raw.strip():
            json.loads(raw)
    except json.JSONDecodeError:
        pass

    project_root = Path.cwd()
    if not (project_root / ".git").exists():
        _emit_json({})
        return 0

    status_out = _run_git(["status", "--porcelain"], project_root)
    if status_out is None:
        _emit_json({})
        return 0

    entries, excluded_count = _parse_porcelain(status_out)
    unstaged_numstat = _parse_numstat(_run_git(["diff", "--numstat"], project_root) or "")
    staged_numstat = _parse_numstat(
        _run_git(["diff", "--cached", "--numstat"], project_root) or ""
    )
    numstat = _merge_numstat(unstaged_numstat, staged_numstat)

    total_added = 0
    total_deleted = 0
    for _, path in entries:
        added, deleted = numstat.get(path, (0, 0))
        total_added += added
        total_deleted += deleted

    if not _should_prompt(entries, total_added, total_deleted):
        _emit_json({})
        return 0

    head_raw = _run_git(["log", "-1", "--oneline"], project_root)
    head_commit = head_raw.strip().splitlines()[0] if head_raw and head_raw.strip() else None

    message = _build_followup(
        entries,
        total_added,
        total_deleted,
        numstat,
        excluded_count,
        head_commit=head_commit,
    )
    _emit_json({"followup_message": message})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

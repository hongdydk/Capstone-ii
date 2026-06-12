#!/usr/bin/env python3
"""Warn when staged backend/issue paths lack staged BUGREPORT.md (non-blocking)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

BUG_BACKEND_PREFIXES = ("backend/", "Engine/")

PATH_ISSUE_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"graphhopper\.py"), "H1"),
    (re.compile(r"rest_stop_inserter"), "H2/H3"),
    (re.compile(r"route_pipeline|replan"), "H4"),
    (re.compile(r"optimize\.py"), "H1/H4"),
    (re.compile(r"config\.py"), "L2"),
)


def _normalize(path: str) -> str:
    return path.replace("\\", "/")


def _is_bugreport(path: str) -> bool:
    return path.rsplit("/", 1)[-1].upper() == "BUGREPORT.MD"


def _is_backend_issue_path(path: str) -> bool:
    if path.startswith(BUG_BACKEND_PREFIXES):
        return True
    return any(p.search(path) for p, _ in PATH_ISSUE_HINTS)


def _issue_hints(paths: list[str]) -> list[str]:
    hints: list[str] = []
    for path in paths:
        basename = path.rsplit("/", 1)[-1]
        for pattern, issue_id in PATH_ISSUE_HINTS:
            if pattern.search(path):
                hints.append(f"{basename}→{issue_id}")
                break
    return sorted(set(hints))


def _staged_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [_normalize(p) for p in result.stdout.splitlines() if p.strip()]


def main() -> int:
    root = Path.cwd()
    if not (root / ".git").exists():
        return 0

    staged = _staged_paths(root)
    if not staged:
        return 0

    backend_staged = [p for p in staged if _is_backend_issue_path(p)]
    if not backend_staged:
        return 0

    if any(_is_bugreport(p) for p in staged):
        return 0

    hints = _issue_hints(backend_staged)
    hint_text = f" ({', '.join(hints)})" if hints else ""
    print(
        "경고: staged 백엔드·이슈 연관 파일이 있으나 BUGREPORT.md가 staged에 없습니다."
        f"{hint_text}\n"
        "  → 구현·결정 반영 시 해당 항목 **상태:** 줄을 BUGREPORT.md에 갱신하고 같은 커밋에 포함하세요.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

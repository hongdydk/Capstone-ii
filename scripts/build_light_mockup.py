#!/usr/bin/env python3
"""Generate control_app_mockup_light.html from dark mockup."""
from pathlib import Path
import re

SRC = Path(__file__).resolve().parents[1] / "frontend_Test" / "control_app_mockup.html"
DST = SRC.parent / "control_app_mockup_light.html"

ROOT_LIGHT = """    :root {
      --lime: #9ae600;
      --lime-dim: #84cc16;
      --lime-glow: rgba(154, 230, 0, .22);
      --primary: #9ae600;
      --primary-dark: #1a1d26;
      --primary-light: #b8f04a;
      --header-h: 76px;
      --sub-nav-reserve: 52px;
      --page-column-max: 1480px;
      --page-column-pad-x: 20px;
      --dark-bg: #f4f6f9;
      --dark-surface: #ffffff;
      --dark-card: #ffffff;
      --dark-border: #e5e8ef;
      --body-bg: #f4f6f9;
      --panel: #ffffff;
      --text: #1a1d26;
      --text-muted: #5c6578;
      --border: #e5e8ef;
      --input-border: #d0d5dd;
      --accent: #3b82f6;
      --accent-dash: #60a5fa;
      --success: #16a34a;
      --excel-green: #22a06b;
      --warning: #b45309;
      --danger: #dc2626;
      --shadow: 0 1px 3px rgba(15, 23, 42, .06);
      --topbar-shadow: 0 1px 0 #e5e8ef, 0 4px 12px rgba(15, 23, 42, .06);
      --radius-lg: 20px;
      --radius-md: 14px;
      --radius-sm: 10px;
    }"""

BODY_BASE = """    body {
      font-family: 'Noto Sans KR', system-ui, sans-serif;
      background: var(--dark-bg);
      color: var(--text);
      min-height: 100vh;
      min-width: 1100px;
    }
    body.theme-light { background: var(--dark-bg); color: var(--text); }
    body.theme-dashboard { background: var(--dark-bg); }"""

TOPBAR = """    .topbar {
      height: var(--header-h);
      background: var(--dark-surface);
      border-bottom: 1px solid var(--dark-border);
      box-shadow: var(--topbar-shadow);
      display: flex;
      align-items: center;
      gap: 20px;
      padding: 0 28px;
      position: sticky;
      top: 0;
      z-index: 100;
      overflow: visible;
    }"""

NAV_SUB = """    .nav-sub-btn {
      border: 1px solid var(--dark-border);
      background: #fff;
      color: var(--text-muted);
      font-family: inherit;
      font-size: 13px;
      font-weight: 600;
      padding: 10px 16px;
      min-height: 40px;
      border-radius: 10px;
      cursor: pointer;
      white-space: nowrap;
      text-align: center;
      transition: background .15s, color .15s, border-color .15s;
    }
    .nav-sub-btn:hover {
      color: var(--text);
      background: #f4f6f9;
      border-color: #d0d5dd;
    }
    .nav-sub-btn.active {
      border-color: var(--lime);
      color: #4d7c0f;
      background: rgba(154, 230, 0, .12);
      box-shadow: 0 0 0 1px rgba(154, 230, 0, .2);
    }"""

NAV_PILL = """    .nav-pill {
      display: flex;
      align-items: center;
      gap: 8px;
      border: none;
      background: transparent;
      color: var(--text-muted);
      font-family: inherit;
      font-size: 13px;
      font-weight: 600;
      padding: 10px 18px;
      min-height: 40px;
      border-radius: 999px;
      cursor: pointer;
      transition: background .15s, color .15s;
    }
    .nav-pill:hover { color: var(--text); background: rgba(15, 23, 42, .05); }
    .nav-pill.active {
      background: var(--lime);
      color: #1a1d26;
      box-shadow: 0 0 0 1px rgba(132, 204, 22, .35);
    }"""

TOPBAR_META = """    .topbar-meta {
      display: flex;
      align-items: center;
      gap: 16px;
      font-size: 12px;
      color: var(--text-muted);
      flex-shrink: 0;
    }
    .topbar-meta strong { color: var(--text); }
    .topbar-user {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: var(--text-muted);
    }
    .topbar-user strong { color: var(--text); font-weight: 600; }
    .topbar-user small { opacity: .65; font-weight: 500; }
    .topbar-icon-btn {
      width: 36px; height: 36px;
      border-radius: 50%;
      border: 1px solid var(--input-border);
      background: #fff;
      color: var(--text-muted);
      cursor: pointer;
      font-size: 14px;
    }"""

PAGE_HEADING = """    body.theme-dashboard .page-heading,
    body.theme-light .page-heading { color: var(--text); }"""

THEME_LIGHT_BLOCK = """
    /* theme-light — app pages (base tokens are light; accent tweaks) */
    body.theme-light .page-desc code { color: #4d7c0f; background: rgba(154,230,0,.12); padding: 1px 4px; border-radius: 4px; }
    body.theme-light input, body.theme-light select, body.theme-light textarea {
      background: #fff;
      border-color: var(--input-border);
      color: var(--text);
    }
    body.theme-light input:focus,
    body.theme-light select:focus,
    body.theme-light textarea:focus {
      border-color: rgba(132,204,22,.55);
      box-shadow: 0 0 0 2px rgba(154,230,0,.15);
    }
    body.theme-light .tab.active { color: #4d7c0f; border-bottom-color: var(--lime); }
    body.theme-light .chip.active { background: var(--lime); color: #1a1d26; border-color: var(--lime); }
    body.theme-light .dispatch-mode-nav button.active {
      background: rgba(154,230,0,.12);
      border-color: rgba(132,204,22,.4);
      color: #4d7c0f;
    }
    body.theme-light .dispatch-mode-nav button.prominent.active {
      background: linear-gradient(135deg, #f0fdf4 0%, #fff 100%);
      color: #4d7c0f;
      border-color: rgba(132,204,22,.45);
    }
    body.theme-light .pagination button.active { background: var(--lime); color: #1a1d26; }
    body.theme-light tbody tr.selected { background: rgba(154,230,0,.1); }
    body.theme-light .link-btn { color: #4d7c0f; }
    body.theme-light .schedule-tabs .chip.active {
      background: rgba(154,230,0,.15);
      color: #4d7c0f;
      border-color: rgba(132,204,22,.4);
    }
    body.theme-light .table-scroll thead th { background: #f0f2f5; color: var(--text-muted); }
    body.theme-light .order-stops-table th,
    body.theme-light .order-history-table th { color: var(--text-muted); }
    body.theme-light .order-stops-table td,
    body.theme-light .order-history-table td { color: var(--text); border-color: var(--border); }
    body.theme-light .toast,
    body.theme-dashboard .toast { background: var(--lime); color: #1a1d26; }
"""

# Remove giant dark theme-app override block
THEME_APP_BLOCK_RE = re.compile(
    r"\n    body\.theme-app \.page-title.*?body\.theme-app \.drawer-ft \.btn-primary:hover \{\n"
    r"      background: var\(--lime-dim\);\n"
    r"      border-color: var\(--lime-dim\);\n"
    r"    \}\n",
    re.DOTALL,
)

COLOR_MAP = [
    ("#0f1117", "#eef1f6"),
    ("#151820", "#f8f9fb"),
    ("#12151c", "#eef1f6"),
    ("#1c2029", "#ffffff"),
    ("#252a35", "#f4f6f9"),
    ("#1a1e28", "#ffffff"),
    ("#4a5168", "#d0d5dd"),
    ("#2a303c", "#e5e8ef"),
    ("#e8eaef", "var(--text)"),
    ("#f3f4f6", "var(--text)"),
    ("#8b93a7", "var(--text-muted)"),
    ("#9ca3af", "var(--text-muted)"),
    ("#c5cad6", "var(--text-muted)"),
    ("#b4bac8", "var(--text-muted)"),
    ("#6b7280", "var(--text-muted)"),
    ("rgba(255,255,255,.08)", "#e5e8ef"),
    ("rgba(255,255,255,.06)", "rgba(15,23,42,.04)"),
    ("rgba(255,255,255,.04)", "rgba(15,23,42,.04)"),
    ("rgba(255,255,255,.03)", "rgba(15,23,42,.03)"),
    ("rgba(255,255,255,.12)", "#d0d5dd"),
    ("rgba(198,241,53,", "rgba(154,230,0,"),
    ("#c6f135", "#9ae600"),
    ("#a8d42e", "#84cc16"),
    ("#93c5fd", "#1d4ed8"),
    ("#fcd34d", "#b45309"),
    ("#86efac", "#15803d"),
    ("#fca5a5", "#dc2626"),
    ("#f87171", "#dc2626"),
]

def replace_block(text: str, start_marker: str, end_marker: str, replacement: str) -> str:
    i = text.find(start_marker)
    if i < 0:
        raise SystemExit(f"marker not found: {start_marker[:40]}")
    j = text.find(end_marker, i)
    if j < 0:
        raise SystemExit(f"end marker not found after: {start_marker[:40]}")
    return text[:i] + replacement + text[j:]


def main() -> None:
    text = SRC.read_text(encoding="utf-8")

    text = text.replace("<title>RouteOn 관제</title>", "<title>RouteOn 관제 (라이트)</title>")

    text = replace_block(text, "    :root {", "    * { box-sizing:", ROOT_LIGHT + "\n")

    text = replace_block(
        text,
        "    body {\n      font-family:",
        "    #app.app-shell {",
        BODY_BASE + "\n",
    )

    text = replace_block(text, "    .topbar {\n      height:", "    .brand {", TOPBAR + "\n")

    text = replace_block(text, "    .nav-sub-btn {", "    .nav-pill {", NAV_SUB + "\n")

    text = replace_block(text, "    .nav-pill {", "    .nav-pill-icon {", NAV_PILL + "\n")

    text = replace_block(text, "    .topbar-meta {", "    .content {", TOPBAR_META + "\n")

    text = text.replace(
        "    body.theme-dashboard .page-heading,\n    body.theme-app .page-heading { color: #f3f4f6; }",
        PAGE_HEADING,
    )

    text, n = THEME_APP_BLOCK_RE.subn("\n", text)
    if n != 1:
        raise SystemExit(f"theme-app block remove count={n}")

    text = text.replace(
        "    body.theme-app .schedule-tabs .chip.active {",
        "    body.theme-light .schedule-tabs .chip.active {",
    )
    text = text.replace("body.theme-app .order-stops-table", "body.theme-light .order-stops-table")
    text = text.replace("body.theme-app .order-history-table", "body.theme-light .order-history-table")
    text = text.replace("body.theme-app .table-scroll", "body.theme-light .table-scroll")
    text = text.replace(
        "    body.theme-dashboard .toast,\n    body.theme-app .toast { background: var(--lime); color: #0c0e12; }",
        "    /* toast: see theme-light block */",
    )

    text = text.replace(
        "    body.theme-dashboard .table-scroll thead th { background: #12151c; }",
        "    body.theme-dashboard .table-scroll thead th { background: #f0f2f5; color: var(--text-muted); }",
    )
    text = text.replace(
        "    body.theme-light .table-scroll thead th { background: #12151c; }",
        "    body.theme-light .table-scroll thead th { background: #f0f2f5; color: var(--text-muted); }",
    )

    # Insert theme-light block before intake-layout-wrap
    text = text.replace(
        "    .intake-layout-wrap {",
        THEME_LIGHT_BLOCK + "    .intake-layout-wrap {",
    )

    # JS theme class
    text = text.replace("theme-dashboard', 'theme-app'", "theme-dashboard', 'theme-light'")
    text = text.replace("classList.add('theme-app')", "classList.add('theme-light')")
    text = text.replace("theme-app(다크)", "theme-light")

    # Map placeholder & driver panel
    text = text.replace(
        """    .map-placeholder {
      min-height: 200px;
      background: #12151c;
      border: 1px solid var(--dark-border);""",
        """    .map-placeholder {
      min-height: 200px;
      background: #eef1f6;
      border: 1px solid var(--border);""",
    )
    text = text.replace(
        """    .driver-panel {
      border: 1px solid var(--dark-border);
      border-radius: var(--radius-md);
      padding: 16px;
      background: #12151c;
    }
    .driver-panel h3 { font-size: 14px; font-weight: 600; color: #f3f4f6; margin-bottom: 8px; }""",
        """    .driver-panel {
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 16px;
      background: #fff;
    }
    .driver-panel h3 { font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 8px; }""",
    )
    text = text.replace(".driver-row:hover { background: rgba(255,255,255,.04); }", ".driver-row:hover { background: #f4f6f9; }")

    text = text.replace(
        """    .task-card {
      background: #12151c;
      border: 1px solid var(--dark-border);
      border-radius: var(--radius-lg);
      padding: 20px 22px;
      margin-bottom: 16px;
      color: #e8eaef;
    }""",
        """    .task-card {
      background: #fff;
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 20px 22px;
      margin-bottom: 16px;
      color: var(--text);
    }""",
    )

    text = text.replace(
        """    .dash-gauge-num {
      position: relative;
      z-index: 1;
      font-size: 28px;
      font-weight: 800;
      color: #fff;""",
        """    .dash-gauge-num {
      position: relative;
      z-index: 1;
      font-size: 28px;
      font-weight: 800;
      color: var(--text);""",
    )

    text = text.replace(".dash-quick-link:hover { border-color: rgba(198,241,53,.35); color: #fff; }", ".dash-quick-link:hover { border-color: rgba(132,204,22,.45); color: var(--text); }")
    text = text.replace(".dash-quick-link strong { display: block; font-size: 12px; color: #fff; margin-bottom: 2px; }", ".dash-quick-link strong { display: block; font-size: 12px; color: var(--text); margin-bottom: 2px; }")

    text = text.replace(
        """    .dash-order-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      padding: 3px;
      background: #12151c;
      border-radius: 999px;
      border: 1px solid var(--dark-border);
    }""",
        """    .dash-order-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      padding: 3px;
      background: #f0f2f5;
      border-radius: 999px;
      border: 1px solid var(--border);
    }""",
    )

    text = text.replace(
        """    .dash-orders-card table th {
      background: #12151c;
      color: #8b93a7;
      border-bottom-color: var(--dark-border);
      font-size: 11px;
    }
    .dash-orders-card table td {
      border-bottom-color: var(--dark-border);
      color: #e8eaef;
      font-size: 12px;
    }
    .dash-orders-card tbody tr:hover { background: rgba(255,255,255,.03); cursor: pointer; }""",
        """    .dash-orders-card table th {
      background: #f0f2f5;
      color: var(--text-muted);
      border-bottom-color: var(--border);
      font-size: 11px;
    }
    .dash-orders-card table td {
      border-bottom-color: var(--border);
      color: var(--text);
      font-size: 12px;
    }
    .dash-orders-card tbody tr:hover { background: #f8f9fb; cursor: pointer; }""",
    )

    text = text.replace("input, select, textarea {\n      font-family: inherit;\n      font-size: 13px;\n      padding: 8px 10px;\n      border: 1px solid var(--border);", "input, select, textarea {\n      font-family: inherit;\n      font-size: 13px;\n      padding: 8px 10px;\n      border: 1px solid var(--input-border);")

    # Bulk color map — <style> only
    style_start = text.index("<style>")
    style_end = text.index("</style>") + len("</style>")
    before, after = text[:style_start], text[style_end:]
    style = text[style_start:style_end]
    for old, new in COLOR_MAP:
        style = style.replace(old, new)
    text = before + style + after

    # Remaining theme-app references -> theme-light
    text = text.replace("theme-app", "theme-light")

    # Nav active text on lime pill
    text = text.replace(".nav-pill.active {\n      background: var(--lime);\n      color: #0c0e12;", ".nav-pill.active {\n      background: var(--lime);\n      color: #1a1d26;")

    text = text.replace(".btn-primary { background: var(--lime); color: #0c0e12;", ".btn-primary { background: var(--lime); color: #1a1d26;")
    text = text.replace(".dash-order-tabs button.active {\n      background: var(--lime);\n      color: #0c0e12;", ".dash-order-tabs button.active {\n      background: var(--lime);\n      color: #1a1d26;")

    DST.write_text(text, encoding="utf-8")
    remaining_app = text.count("theme-app")
    print(f"Wrote {DST} ({len(text.splitlines())} lines), remaining theme-app: {remaining_app}")


if __name__ == "__main__":
    main()

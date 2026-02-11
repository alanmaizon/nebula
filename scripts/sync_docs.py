#!/usr/bin/env python3
"""Synchronize Markdown status sections from docs/status.yml.

`docs/status.yml` uses JSON syntax so this script can parse it with
Python's standard library.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "docs" / "status.yml"


STATUS_LABELS = {
    "not_started": "Not started",
    "in_progress": "In progress",
    "done": "Done",
    "blocked": "Blocked",
    "partial": "Partial",
}


def _label(value: str) -> str:
    return STATUS_LABELS.get(value, value.replace("_", " ").title())


def _load_status() -> dict:
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Status file not found: {STATUS_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {STATUS_PATH}: {exc}") from exc


def _phase_rows(status: dict) -> list[dict]:
    phases = status.get("phases")
    if phases:
        return phases
    return status.get("weeks", [])


def _pick_current_phase(status: dict) -> dict:
    phases = _phase_rows(status)
    current_phase = status.get("current_phase")
    if current_phase:
        for phase in phases:
            if phase.get("id") == current_phase:
                return phase

    # Backward compatibility for numeric current_week status files.
    current_week = status.get("current_week")
    if current_week is not None:
        for phase in phases:
            if phase.get("week") == current_week:
                return phase
    return phases[0] if phases else {}


def _render_list(title: str, items: list[str], empty_text: str) -> list[str]:
    lines = [f"### {title}"]
    if items:
        lines.extend([f"- {item}" for item in items])
    else:
        lines.append(f"- {empty_text}")
    return lines


def render_readme_status(status: dict) -> str:
    current = _pick_current_phase(status)
    lines = [
        f"- Last updated: `{status.get('last_updated', 'unknown')}`",
        f"- Overall completion: `{status.get('overall_completion_pct', 0)}%`",
    ]
    if current:
        lines.append(
            f"- Current phase: `{current.get('focus', 'Unknown')} "
            f"({_label(current.get('status', 'not_started'))})`"
        )

    lines.append("")
    lines.extend(
        _render_list(
            "Done Recently",
            current.get("done", []),
            "No completed items recorded yet.",
        )
    )
    lines.append("")
    lines.extend(
        _render_list(
            "Next Up",
            current.get("next", []),
            "No upcoming items recorded yet.",
        )
    )
    lines.append("")
    lines.extend(
        _render_list(
            "Current Blockers",
            current.get("blockers", []),
            "No blockers recorded.",
        )
    )
    return "\n".join(lines)


def render_development_status(status: dict) -> str:
    phases = _phase_rows(status)
    lines = [
        "| Focus | Status |",
        "|---|---|",
    ]
    for phase in phases:
        lines.append(
            f"| {phase.get('focus', 'Unknown')} | "
            f"{_label(phase.get('status', 'not_started'))} |"
        )

    current = _pick_current_phase(status)
    lines.append("")
    lines.extend(
        _render_list(
            "Current Priorities",
            current.get("next", []),
            "No priorities recorded.",
        )
    )
    lines.append("")
    risk_rows = status.get("high_risks", [])
    lines.append("### Active Risks")
    if risk_rows:
        lines.extend(
            [f"- {entry.get('risk', 'Unnamed risk')} -> {entry.get('mitigation', 'No mitigation')}" for entry in risk_rows]
        )
    else:
        lines.append("- No active risks recorded.")

    return "\n".join(lines)


def render_aws_status(status: dict) -> str:
    pillars = status.get("aws", {}).get("well_architected", [])
    lines = [
        f"- Last updated: `{status.get('last_updated', 'unknown')}`",
        "",
        "| Pillar | Status | Next Control |",
        "|---|---|---|",
    ]
    for pillar in pillars:
        lines.append(
            f"| {pillar.get('pillar', 'Unknown')} | "
            f"{_label(pillar.get('status', 'not_started'))} | "
            f"{pillar.get('next_control', 'Not set')} |"
        )
    return "\n".join(lines)


def _replace_block(file_text: str, block_name: str, generated_body: str) -> str:
    start = f"<!-- AUTO-GEN:{block_name}:START -->"
    end = f"<!-- AUTO-GEN:{block_name}:END -->"
    pattern = re.compile(
        re.escape(start) + r"\n.*?\n" + re.escape(end),
        flags=re.DOTALL,
    )
    replacement = f"{start}\n{generated_body.strip()}\n{end}"
    updated_text, count = pattern.subn(replacement, file_text, count=1)
    if count != 1:
        raise SystemExit(f"Could not find block {block_name} in target document.")
    return updated_text


def _sync_file(
    relative_path: str,
    block_name: str,
    renderer: Callable[[dict], str],
    status: dict,
    check: bool,
) -> bool:
    path = ROOT / relative_path
    original = path.read_text(encoding="utf-8")
    generated = renderer(status)
    updated = _replace_block(original, block_name, generated)
    changed = updated != original
    if changed and not check:
        path.write_text(updated, encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync generated documentation sections from docs/status.yml"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate docs are up to date without writing changes.",
    )
    args = parser.parse_args()

    status = _load_status()
    targets = [
        ("README.md", "README_STATUS", render_readme_status),
        ("docs/wiki/DEVELOPMENT_PLAN.md", "DEVELOPMENT_PLAN_STATUS", render_development_status),
        ("docs/wiki/AWS_ALIGNMENT.md", "AWS_STATUS", render_aws_status),
    ]

    changed_paths: list[str] = []
    for relative_path, block_name, renderer in targets:
        changed = _sync_file(relative_path, block_name, renderer, status, args.check)
        if changed:
            changed_paths.append(relative_path)

    if args.check and changed_paths:
        print("Documentation is out of date. Run: python scripts/sync_docs.py")
        for path in changed_paths:
            print(f"- {path}")
        return 1

    if not args.check:
        if changed_paths:
            print("Updated documentation:")
            for path in changed_paths:
                print(f"- {path}")
        else:
            print("No documentation changes needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

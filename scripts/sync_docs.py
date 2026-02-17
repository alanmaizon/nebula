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


def _schema_error(message: str) -> SystemExit:
    return SystemExit(
        f"Invalid status schema in {STATUS_PATH}: {message} "
        "(use phase-only fields: current_phase + phases[])."
    )


def _require_string(
    value: object,
    field: str,
    *,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise _schema_error(f"Field '{field}' must be a string.")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise _schema_error(f"Field '{field}' must not be empty.")
    return normalized


def _require_status(value: object, field: str) -> str:
    normalized = _require_string(value, field)
    if normalized not in STATUS_LABELS:
        allowed = ", ".join(sorted(STATUS_LABELS))
        raise _schema_error(f"Field '{field}' has unsupported status '{normalized}' (allowed: {allowed}).")
    return normalized


def _require_string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise _schema_error(f"Field '{field}' must be a list of strings.")
    items: list[str] = []
    for index, raw in enumerate(value):
        items.append(_require_string(raw, f"{field}[{index}]"))
    return items


def validate_status_schema(raw_status: object) -> dict:
    if not isinstance(raw_status, dict):
        raise _schema_error("Top-level payload must be an object.")

    status = dict(raw_status)
    if "weeks" in status or "current_week" in status:
        raise _schema_error(
            "Legacy keys 'weeks'/'current_week' are no longer supported; migrate to 'phases'/'current_phase'."
        )

    phases_raw = status.get("phases")
    if not isinstance(phases_raw, list) or not phases_raw:
        raise _schema_error("Field 'phases' must be a non-empty list.")

    phases: list[dict] = []
    phase_ids: set[str] = set()
    for index, raw_phase in enumerate(phases_raw):
        if not isinstance(raw_phase, dict):
            raise _schema_error(f"Field 'phases[{index}]' must be an object.")
        if "week" in raw_phase:
            raise _schema_error("Field 'phases[].week' is no longer supported.")

        phase_id = _require_string(raw_phase.get("id"), f"phases[{index}].id")
        if phase_id in phase_ids:
            raise _schema_error(f"Field 'phases[{index}].id' duplicates id '{phase_id}'.")
        phase_ids.add(phase_id)

        phases.append(
            {
                "id": phase_id,
                "focus": _require_string(raw_phase.get("focus"), f"phases[{index}].focus"),
                "status": _require_status(raw_phase.get("status"), f"phases[{index}].status"),
                "done": _require_string_list(raw_phase.get("done", []), f"phases[{index}].done"),
                "next": _require_string_list(raw_phase.get("next", []), f"phases[{index}].next"),
                "blockers": _require_string_list(raw_phase.get("blockers", []), f"phases[{index}].blockers"),
            }
        )

    current_phase = _require_string(status.get("current_phase"), "current_phase")
    if current_phase not in phase_ids:
        raise _schema_error("Field 'current_phase' must match one of 'phases[].id'.")

    last_updated = _require_string(status.get("last_updated"), "last_updated")
    overall_completion = status.get("overall_completion_pct")
    if not isinstance(overall_completion, (int, float)):
        raise _schema_error("Field 'overall_completion_pct' must be numeric.")

    high_risks_raw = status.get("high_risks", [])
    if not isinstance(high_risks_raw, list):
        raise _schema_error("Field 'high_risks' must be a list.")
    high_risks: list[dict] = []
    for index, raw_risk in enumerate(high_risks_raw):
        if not isinstance(raw_risk, dict):
            raise _schema_error(f"Field 'high_risks[{index}]' must be an object.")
        high_risks.append(
            {
                "risk": _require_string(raw_risk.get("risk"), f"high_risks[{index}].risk"),
                "mitigation": _require_string(raw_risk.get("mitigation"), f"high_risks[{index}].mitigation"),
            }
        )

    aws_raw = status.get("aws", {})
    if not isinstance(aws_raw, dict):
        raise _schema_error("Field 'aws' must be an object.")
    pillars_raw = aws_raw.get("well_architected", [])
    if not isinstance(pillars_raw, list):
        raise _schema_error("Field 'aws.well_architected' must be a list.")
    pillars: list[dict] = []
    for index, raw_pillar in enumerate(pillars_raw):
        if not isinstance(raw_pillar, dict):
            raise _schema_error(f"Field 'aws.well_architected[{index}]' must be an object.")
        pillars.append(
            {
                "pillar": _require_string(raw_pillar.get("pillar"), f"aws.well_architected[{index}].pillar"),
                "status": _require_status(raw_pillar.get("status"), f"aws.well_architected[{index}].status"),
                "next_control": _require_string(
                    raw_pillar.get("next_control"),
                    f"aws.well_architected[{index}].next_control",
                ),
            }
        )

    normalized: dict[str, object] = {
        "last_updated": last_updated,
        "overall_completion_pct": overall_completion,
        "current_phase": current_phase,
        "phases": phases,
        "high_risks": high_risks,
        "aws": {"well_architected": pillars},
    }
    project = status.get("project")
    if project is not None:
        normalized["project"] = _require_string(project, "project")
    return normalized


def _load_status() -> dict:
    try:
        parsed = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Status file not found: {STATUS_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {STATUS_PATH}: {exc}") from exc
    return validate_status_schema(parsed)


def _pick_current_phase(status: dict) -> dict:
    phases = status.get("phases", [])
    current_phase = status.get("current_phase")
    if current_phase:
        for phase in phases:
            if phase.get("id") == current_phase:
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
    phases = status.get("phases", [])
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

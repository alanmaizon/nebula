#!/usr/bin/env python3
"""Validate release/version consistency across runtime and release docs."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / "backend" / "app" / "version.py"
MAIN_FILE = REPO_ROOT / "backend" / "app" / "main.py"
HOME_FILE = REPO_ROOT / "docs" / "wiki" / "Home.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_app_version(version_text: str) -> str | None:
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"\s*$', version_text, flags=re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


def _validate_semver(version: str) -> bool:
    return re.fullmatch(r"\d+\.\d+\.\d+", version) is not None


def main() -> int:
    errors: list[str] = []

    if not VERSION_FILE.exists():
        errors.append(f"Missing version source: {VERSION_FILE}")
    if not MAIN_FILE.exists():
        errors.append(f"Missing backend app entrypoint: {MAIN_FILE}")
    if not HOME_FILE.exists():
        errors.append(f"Missing wiki home page: {HOME_FILE}")
    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        return 1

    version_text = _read(VERSION_FILE)
    app_version = _parse_app_version(version_text)
    if app_version is None:
        errors.append(f"Could not parse APP_VERSION from {VERSION_FILE}")
        app_version = "unknown"
    elif not _validate_semver(app_version):
        errors.append(f"APP_VERSION must follow X.Y.Z semantic versioning, found: {app_version}")

    main_text = _read(MAIN_FILE)
    if "from app.version import APP_VERSION" not in main_text:
        errors.append("backend/app/main.py must import APP_VERSION from app.version.")
    if re.search(r"FastAPI\([^)]*version\s*=\s*APP_VERSION", main_text, flags=re.DOTALL) is None:
        errors.append("backend/app/main.py must set FastAPI version=APP_VERSION.")

    release_notes = REPO_ROOT / "docs" / "wiki" / f"Release-Notes-v{app_version}.md"
    if not release_notes.exists():
        errors.append(f"Release notes missing for current version: {release_notes}")
    else:
        notes_text = _read(release_notes)
        expected_header = f"# Release Notes - v{app_version}"
        if expected_header not in notes_text:
            errors.append(
                f"{release_notes} must include header '{expected_header}'."
            )

    home_text = _read(HOME_FILE)
    expected_link = f"[Release Notes v{app_version}](Release-Notes-v{app_version})"
    if expected_link not in home_text:
        errors.append(f"docs/wiki/Home.md must include link '{expected_link}'.")

    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        return 1

    print(f"[OK] Release consistency checks passed for v{app_version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

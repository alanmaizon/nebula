import re

from app.main import app
from app.version import APP_VERSION


def test_fastapi_uses_centralized_app_version() -> None:
    assert app.version == APP_VERSION


def test_app_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", APP_VERSION)

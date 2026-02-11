#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
ITERATIONS="${ITERATIONS:-3}"

TESTS=(
  "tests/test_health.py::test_create_project_and_upload"
  "tests/test_health.py::test_retrieve_is_project_scoped"
  "tests/test_health.py::test_extract_requirements_and_read_latest"
  "tests/test_health.py::test_generate_section_and_read_latest_draft"
  "tests/test_health.py::test_compute_coverage_and_read_latest"
  "tests/test_health.py::test_export_json_and_markdown"
  "tests/test_nova_runtime.py::test_nova_orchestrator_uses_expected_models"
)

echo "Running deterministic submission-critical backend tests"
echo "Iterations: ${ITERATIONS}"
echo "Test set:"
for test_name in "${TESTS[@]}"; do
  echo "- ${test_name}"
done
echo

cd "${BACKEND_DIR}"
PYTEST_BIN=".venv/bin/pytest"
if [[ ! -x "${PYTEST_BIN}" ]]; then
  if command -v pytest >/dev/null 2>&1; then
    PYTEST_BIN="$(command -v pytest)"
  else
    echo "pytest is not available (.venv/bin/pytest or PATH)." >&2
    exit 127
  fi
fi

for i in $(seq 1 "${ITERATIONS}"); do
  echo "[${i}/${ITERATIONS}] running deterministic test set..."
  PYTHONPATH=. "${PYTEST_BIN}" -q "${TESTS[@]}"
done

echo
echo "Deterministic test set passed for ${ITERATIONS}/${ITERATIONS} runs."

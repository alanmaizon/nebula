#!/usr/bin/env bash
set -euo pipefail

RUN_LABEL="${1:-}"
if [ -z "${RUN_LABEL}" ]; then
  echo "usage: scripts/run_demo_freeze.sh <run-label>" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="/tmp/nebula-demo-freeze/${RUN_LABEL}"
API_BASE="${API_BASE:-http://localhost:8000}"
SECTION_KEY="${SECTION_KEY:-Need Statement}"

mkdir -p "${OUT_DIR}"

wait_for_health() {
  local url="$1"
  local attempts="${2:-60}"
  local i
  for i in $(seq 1 "${attempts}"); do
    if curl --silent --show-error --fail --connect-timeout 2 --max-time 5 "${url}" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "health check failed: ${url}" >&2
  return 1
}

write_fixtures() {
  cat > "${OUT_DIR}/rfp.txt" <<'EOF'
Funder: City Community Fund
Deadline: March 30, 2026

Question 1: Describe program outcomes. Limit 250 words.
Question 2: Explain implementation timeline. Limit 500 words.

Required Attachments:
- Attachment A: Budget Narrative
- Attachment B: Board List

Rubric:
- Scoring criteria include impact and feasibility.

Disallowed costs:
- Alcohol purchases are not allowed costs.
EOF

  cat > "${OUT_DIR}/impact.txt" <<'EOF'
Need Statement:
We served 1240 households in 2024 with emergency housing support.
Our implementation timeline spans four quarters with milestones.
EOF
}

wait_for_health "${API_BASE}/health"
wait_for_health "${API_BASE}/ready"
write_fixtures

project_response="$(curl -sS -X POST "${API_BASE}/projects" -H "Content-Type: application/json" -d "{\"name\":\"Demo Freeze ${RUN_LABEL}\"}")"
project_id="$(PROJECT_RESPONSE="${project_response}" python3 - <<'PY'
import json
import os
print(json.loads(os.environ["PROJECT_RESPONSE"])["id"])
PY
)"

upload_status="$(curl -sS -o "${OUT_DIR}/upload.json" -w '%{http_code}' -X POST \
  "${API_BASE}/projects/${project_id}/upload" \
  -F "files=@${OUT_DIR}/rfp.txt;type=text/plain" \
  -F "files=@${OUT_DIR}/impact.txt;type=text/plain")"

extract_status="$(curl -sS -o "${OUT_DIR}/extract.json" -w '%{http_code}' -X POST \
  "${API_BASE}/projects/${project_id}/extract-requirements")"

generate_status="$(curl -sS -o "${OUT_DIR}/generate.json" -w '%{http_code}' -X POST \
  "${API_BASE}/projects/${project_id}/generate-section" \
  -H "Content-Type: application/json" \
  -d "{\"section_key\":\"${SECTION_KEY}\",\"top_k\":3}")"

coverage_status="$(curl -sS -o "${OUT_DIR}/coverage.json" -w '%{http_code}' -X POST \
  "${API_BASE}/projects/${project_id}/coverage" \
  -H "Content-Type: application/json" \
  -d "{\"section_key\":\"${SECTION_KEY}\"}")"

export_json_status="$(curl -sS -o "${OUT_DIR}/export.json" -w '%{http_code}' \
  "${API_BASE}/projects/${project_id}/export?format=json&section_key=${SECTION_KEY// /%20}")"

export_md_status="$(curl -sS -o "${OUT_DIR}/export.md" -w '%{http_code}' \
  "${API_BASE}/projects/${project_id}/export?format=markdown&section_key=${SECTION_KEY// /%20}")"

if [ "${upload_status}" != "200" ] || [ "${extract_status}" != "200" ] || [ "${generate_status}" != "200" ] || [ "${coverage_status}" != "200" ] || [ "${export_json_status}" != "200" ] || [ "${export_md_status}" != "200" ]; then
  echo "pipeline status failure: upload=${upload_status} extract=${extract_status} generate=${generate_status} coverage=${coverage_status} export_json=${export_json_status} export_md=${export_md_status}" >&2
  exit 1
fi

python3 - <<'PY' "${OUT_DIR}/extract.json" "${OUT_DIR}/generate.json" "${OUT_DIR}/coverage.json" "${OUT_DIR}/export.json"
import json
import sys
extract_path, generate_path, coverage_path, export_path = sys.argv[1:5]
extract = json.load(open(extract_path, "r", encoding="utf-8"))
generate = json.load(open(generate_path, "r", encoding="utf-8"))
coverage = json.load(open(coverage_path, "r", encoding="utf-8"))
export_payload = json.load(open(export_path, "r", encoding="utf-8"))

assert len(extract["requirements"]["questions"]) >= 2
assert len(generate["draft"]["paragraphs"]) >= 1
assert len(coverage["coverage"]["items"]) >= 1
assert export_payload["requirements"] is not None
assert export_payload["draft"] is not None
assert export_payload["coverage"] is not None
PY

cat > "${OUT_DIR}/summary.txt" <<EOF
run_label=${RUN_LABEL}
project_id=${project_id}
upload_status=${upload_status}
extract_status=${extract_status}
generate_status=${generate_status}
coverage_status=${coverage_status}
export_json_status=${export_json_status}
export_md_status=${export_md_status}
artifact_dir=${OUT_DIR}
EOF

cat "${OUT_DIR}/summary.txt"

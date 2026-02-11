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

full_draft_status="$(curl -sS -o "${OUT_DIR}/full_draft.json" -w '%{http_code}' -X POST \
  "${API_BASE}/projects/${project_id}/generate-full-draft?profile=submission" \
  -H "Content-Type: application/json" \
  -d "{\"top_k\":3,\"max_revision_rounds\":1}")"

export_json_status="$(curl -sS -o "${OUT_DIR}/export.json" -w '%{http_code}' \
  "${API_BASE}/projects/${project_id}/export?format=json&profile=submission")"

export_md_status="$(curl -sS -o "${OUT_DIR}/export.md" -w '%{http_code}' \
  "${API_BASE}/projects/${project_id}/export?format=markdown&profile=submission")"

if [ "${upload_status}" != "200" ] || [ "${full_draft_status}" != "200" ] || [ "${export_json_status}" != "200" ] || [ "${export_md_status}" != "200" ]; then
  echo "pipeline status failure: upload=${upload_status} full_draft=${full_draft_status} export_json=${export_json_status} export_md=${export_md_status}" >&2
  exit 1
fi

python3 - <<'PY' "${OUT_DIR}/full_draft.json" "${OUT_DIR}/export.json"
import json
import sys
full_draft_path, export_path = sys.argv[1:3]
full = json.load(open(full_draft_path, "r", encoding="utf-8"))
export_payload = json.load(open(export_path, "r", encoding="utf-8"))

assert full["requirements"] is not None
assert len(full["section_runs"]) >= 1
assert full["coverage"] is not None
assert len(full["coverage"]["items"]) >= 1
assert full["export"] is not None
assert export_payload["export_version"] == "nebula.export.v1"
assert export_payload["bundle"]["json"]["requirements"] is not None
assert export_payload["bundle"]["json"]["drafts"] is not None
assert export_payload["bundle"]["json"]["coverage"] is not None
assert len(export_payload["bundle"]["markdown"]["files"]) >= 1
PY

cat > "${OUT_DIR}/summary.txt" <<EOF
run_label=${RUN_LABEL}
project_id=${project_id}
upload_status=${upload_status}
full_draft_status=${full_draft_status}
export_json_status=${export_json_status}
export_md_status=${export_md_status}
artifact_dir=${OUT_DIR}
EOF

cat "${OUT_DIR}/summary.txt"

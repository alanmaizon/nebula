#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/aws/render_github_actions_settings_from_tf.sh <terraform-output-json> [repo]

Example:
  terraform output -json > tf-output.json
  scripts/aws/render_github_actions_settings_from_tf.sh tf-output.json alanmaizon/nebula
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

OUTPUT_JSON="${1:-}"
REPO="${2:-alanmaizon/nebula}"

if [[ -z "${OUTPUT_JSON}" || ! -f "${OUTPUT_JSON}" ]]; then
  usage >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required." >&2
  exit 1
fi

echo "# GitHub Actions secrets"
jq -r --arg repo "${REPO}" '
  .github_actions_secrets.value
  | to_entries[]
  | "gh secret set \(.key) --repo \($repo) --body \(.value | @sh)"
' "${OUTPUT_JSON}"

echo
echo "# GitHub Actions variables"
jq -r --arg repo "${REPO}" '
  .github_actions_vars.value
  | to_entries[]
  | "gh variable set \(.key) --repo \($repo) --body \(.value | @sh)"
' "${OUTPUT_JSON}"

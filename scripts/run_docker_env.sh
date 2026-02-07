#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILES=(-f "${ROOT_DIR}/docker-compose.runtime.yml")
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nebula}"

wait_for_http() {
  local url="$1"
  local max_attempts="${2:-60}"
  local sleep_seconds="${3:-2}"
  local attempt=1

  while (( attempt <= max_attempts )); do
    if curl --silent --show-error --fail --connect-timeout 2 --max-time 5 "${url}" > /dev/null; then
      echo "healthy: ${url}"
      return 0
    fi
    sleep "${sleep_seconds}"
    attempt=$((attempt + 1))
  done

  echo "timed out waiting for ${url}" >&2
  return 1
}

up() {
  docker compose "${COMPOSE_FILES[@]}" --project-name "${PROJECT_NAME}" up -d --build
}

down() {
  docker compose "${COMPOSE_FILES[@]}" --project-name "${PROJECT_NAME}" down --remove-orphans
}

logs() {
  docker compose "${COMPOSE_FILES[@]}" --project-name "${PROJECT_NAME}" logs -f --tail=200
}

test_stack() {
  wait_for_http "http://localhost:8000/health"
  wait_for_http "http://localhost:3000/api/health"
  echo "stack smoke test passed"
}

usage() {
  cat <<'EOF'
Usage: scripts/run_docker_env.sh <command>

Commands:
  up      Build and start docker environment
  test    Run smoke tests against running containers
  logs    Follow container logs
  down    Stop and remove containers
  restart Recreate the environment and run smoke tests
EOF
}

main() {
  local cmd="${1:-}"

  case "${cmd}" in
    up)
      up
      ;;
    test)
      test_stack
      ;;
    logs)
      logs
      ;;
    down)
      down
      ;;
    restart)
      down || true
      up
      test_stack
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"

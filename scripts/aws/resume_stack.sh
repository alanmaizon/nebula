#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/aws/resume_stack.sh [options]

Resume Nebula AWS runtime by starting RDS and scaling ECS services back up.

Options:
  --profile PROFILE            AWS profile (default: $AWS_PROFILE or nebula)
  --region REGION              AWS region (default: $AWS_REGION or eu-central-1)
  --cluster NAME               ECS cluster name (default: $ECS_CLUSTER or nebula-cluster)
  --backend-service NAME       Backend ECS service name (default: $ECS_BACKEND_SERVICE or nebula-backend)
  --frontend-service NAME      Frontend ECS service name (default: $ECS_FRONTEND_SERVICE or nebula-frontend)
  --db-instance NAME           RDS DB instance identifier (default: $DB_INSTANCE_ID or nebula-postgres)
  --backend-count N            Backend desired count (default: 1)
  --frontend-count N           Frontend desired count (default: 1)
  --skip-db                    Skip RDS start step
  -h, --help                   Show help
USAGE
}

PROFILE="${AWS_PROFILE:-nebula}"
REGION="${AWS_REGION:-eu-central-1}"
CLUSTER="${ECS_CLUSTER:-nebula-cluster}"
BACKEND_SERVICE="${ECS_BACKEND_SERVICE:-nebula-backend}"
FRONTEND_SERVICE="${ECS_FRONTEND_SERVICE:-nebula-frontend}"
DB_INSTANCE="${DB_INSTANCE_ID:-nebula-postgres}"
BACKEND_COUNT=1
FRONTEND_COUNT=1
SKIP_DB=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      PROFILE="$2"
      shift 2
      ;;
    --region)
      REGION="$2"
      shift 2
      ;;
    --cluster)
      CLUSTER="$2"
      shift 2
      ;;
    --backend-service)
      BACKEND_SERVICE="$2"
      shift 2
      ;;
    --frontend-service)
      FRONTEND_SERVICE="$2"
      shift 2
      ;;
    --db-instance)
      DB_INSTANCE="$2"
      shift 2
      ;;
    --backend-count)
      BACKEND_COUNT="$2"
      shift 2
      ;;
    --frontend-count)
      FRONTEND_COUNT="$2"
      shift 2
      ;;
    --skip-db)
      SKIP_DB=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

AWS_CMD=(aws --profile "$PROFILE" --region "$REGION")

echo "Checking AWS identity..."
"${AWS_CMD[@]}" sts get-caller-identity >/dev/null

service_is_active() {
  local service_name="$1"
  local status
  status="$("${AWS_CMD[@]}" ecs describe-services \
    --cluster "$CLUSTER" \
    --services "$service_name" \
    --query 'services[0].status' \
    --output text 2>/dev/null || true)"
  [[ "$status" == "ACTIVE" ]]
}

if [[ "$SKIP_DB" -eq 0 ]]; then
  db_status="$("${AWS_CMD[@]}" rds describe-db-instances \
    --db-instance-identifier "$DB_INSTANCE" \
    --query 'DBInstances[0].DBInstanceStatus' \
    --output text 2>/dev/null || true)"
  case "$db_status" in
    available)
      echo "RDS instance '$DB_INSTANCE' already available."
      ;;
    stopped)
      echo "Starting RDS instance '$DB_INSTANCE'..."
      "${AWS_CMD[@]}" rds start-db-instance \
        --db-instance-identifier "$DB_INSTANCE" >/dev/null
      echo "Waiting for RDS instance to become available..."
      "${AWS_CMD[@]}" rds wait db-instance-available \
        --db-instance-identifier "$DB_INSTANCE"
      ;;
    starting)
      echo "RDS instance '$DB_INSTANCE' is already starting. Waiting for availability..."
      "${AWS_CMD[@]}" rds wait db-instance-available \
        --db-instance-identifier "$DB_INSTANCE"
      ;;
    "")
      echo "Skipping RDS start: instance '$DB_INSTANCE' not found."
      ;;
    *)
      echo "Skipping RDS start: instance '$DB_INSTANCE' is in status '$db_status'."
      ;;
  esac
fi

UPDATED_SERVICES=()

if service_is_active "$BACKEND_SERVICE"; then
  echo "Scaling ECS service '$BACKEND_SERVICE' to $BACKEND_COUNT..."
  "${AWS_CMD[@]}" ecs update-service \
    --cluster "$CLUSTER" \
    --service "$BACKEND_SERVICE" \
    --desired-count "$BACKEND_COUNT" >/dev/null
  UPDATED_SERVICES+=("$BACKEND_SERVICE")
else
  echo "Skipping backend service '$BACKEND_SERVICE' (not found or not ACTIVE)."
fi

if [[ -n "$FRONTEND_SERVICE" ]] && service_is_active "$FRONTEND_SERVICE"; then
  echo "Scaling ECS service '$FRONTEND_SERVICE' to $FRONTEND_COUNT..."
  "${AWS_CMD[@]}" ecs update-service \
    --cluster "$CLUSTER" \
    --service "$FRONTEND_SERVICE" \
    --desired-count "$FRONTEND_COUNT" >/dev/null
  UPDATED_SERVICES+=("$FRONTEND_SERVICE")
else
  if [[ -n "$FRONTEND_SERVICE" ]]; then
    echo "Skipping frontend service '$FRONTEND_SERVICE' (not found or not ACTIVE)."
  fi
fi

if [[ ${#UPDATED_SERVICES[@]} -gt 0 ]]; then
  echo "Waiting for ECS services to stabilize..."
  "${AWS_CMD[@]}" ecs wait services-stable \
    --cluster "$CLUSTER" \
    --services "${UPDATED_SERVICES[@]}"
fi

echo
echo "Resume complete."
echo "If UI looks stale, run CloudFront invalidation for '/' and '/_next/static/*'."

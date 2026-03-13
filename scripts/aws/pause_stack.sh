#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/aws/pause_stack.sh [options]

Pause Nebula AWS runtime costs by scaling ECS services to 0 and stopping RDS.

Options:
  --profile PROFILE            AWS profile (optional)
  --region REGION              AWS region (default: $AWS_REGION or eu-central-1)
  --cluster NAME               ECS cluster name (default: $ECS_CLUSTER or nebula-cluster)
  --backend-service NAME       Backend ECS service name (default: $ECS_BACKEND_SERVICE or nebula-backend)
  --frontend-service NAME      Frontend ECS service name (default: $ECS_FRONTEND_SERVICE or nebula-frontend)
  --db-instance NAME           RDS DB identifier (instance or cluster; default: $DB_INSTANCE_ID)
  --skip-db                    Skip RDS stop step
  -h, --help                   Show help
USAGE
}

PROFILE="${AWS_PROFILE:-}"
REGION="${AWS_REGION:-eu-central-1}"
CLUSTER="${ECS_CLUSTER:-nebula-cluster}"
BACKEND_SERVICE="${ECS_BACKEND_SERVICE:-nebula-backend}"
FRONTEND_SERVICE="${ECS_FRONTEND_SERVICE:-nebula-frontend}"
DB_INSTANCE="${DB_INSTANCE_ID:-}"
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

AWS_CMD=(aws --region "$REGION")
if [[ -n "$PROFILE" ]]; then
  AWS_CMD+=(--profile "$PROFILE")
fi

echo "Checking AWS identity..."
"${AWS_CMD[@]}" sts get-caller-identity >/dev/null

aws_json() {
  "${AWS_CMD[@]}" "$@"
}

service_is_active() {
  local service_name="$1"
  local status
  status="$(aws_json ecs describe-services \
    --cluster "$CLUSTER" \
    --services "$service_name" \
    --query 'services[0].status' \
    --output text 2>/dev/null || true)"
  [[ "$status" == "ACTIVE" ]]
}

detect_db_kind() {
  local identifier="$1"
  if aws_json rds describe-db-instances --db-instance-identifier "$identifier" >/dev/null 2>&1; then
    echo "instance"
    return 0
  fi
  if aws_json rds describe-db-clusters --db-cluster-identifier "$identifier" >/dev/null 2>&1; then
    echo "cluster"
    return 0
  fi
  return 1
}

UPDATED_SERVICES=()

if service_is_active "$BACKEND_SERVICE"; then
  echo "Scaling ECS service '$BACKEND_SERVICE' to 0..."
  aws_json ecs update-service \
    --cluster "$CLUSTER" \
    --service "$BACKEND_SERVICE" \
    --desired-count 0 >/dev/null
  UPDATED_SERVICES+=("$BACKEND_SERVICE")
else
  echo "Skipping backend service '$BACKEND_SERVICE' (not found or not ACTIVE)."
fi

if [[ -n "$FRONTEND_SERVICE" ]] && service_is_active "$FRONTEND_SERVICE"; then
  echo "Scaling ECS service '$FRONTEND_SERVICE' to 0..."
  aws_json ecs update-service \
    --cluster "$CLUSTER" \
    --service "$FRONTEND_SERVICE" \
    --desired-count 0 >/dev/null
  UPDATED_SERVICES+=("$FRONTEND_SERVICE")
else
  if [[ -n "$FRONTEND_SERVICE" ]]; then
    echo "Skipping frontend service '$FRONTEND_SERVICE' (not found or not ACTIVE)."
  fi
fi

if [[ ${#UPDATED_SERVICES[@]} -gt 0 ]]; then
  echo "Waiting for ECS services to stabilize..."
  aws_json ecs wait services-stable \
    --cluster "$CLUSTER" \
    --services "${UPDATED_SERVICES[@]}"
fi

if [[ "$SKIP_DB" -eq 0 ]]; then
  if [[ -z "$DB_INSTANCE" ]]; then
    echo "Skipping RDS stop: DB_INSTANCE_ID was not provided."
  else
    DB_KIND="$(detect_db_kind "$DB_INSTANCE" || true)"
    case "$DB_KIND" in
      instance)
        db_status="$(aws_json rds describe-db-instances \
          --db-instance-identifier "$DB_INSTANCE" \
          --query 'DBInstances[0].DBInstanceStatus' \
          --output text 2>/dev/null || true)"
        case "$db_status" in
          available)
            echo "Stopping RDS instance '$DB_INSTANCE'..."
            aws_json rds stop-db-instance \
              --db-instance-identifier "$DB_INSTANCE" >/dev/null
            ;;
          stopping|stopped)
            echo "RDS instance '$DB_INSTANCE' already $db_status."
            ;;
          *)
            echo "Skipping RDS instance '$DB_INSTANCE': status '$db_status'."
            ;;
        esac
        ;;
      cluster)
        db_status="$(aws_json rds describe-db-clusters \
          --db-cluster-identifier "$DB_INSTANCE" \
          --query 'DBClusters[0].Status' \
          --output text 2>/dev/null || true)"
        case "$db_status" in
          available)
            echo "Stopping RDS cluster '$DB_INSTANCE'..."
            aws_json rds stop-db-cluster \
              --db-cluster-identifier "$DB_INSTANCE" >/dev/null
            ;;
          stopping|stopped)
            echo "RDS cluster '$DB_INSTANCE' already $db_status."
            ;;
          *)
            echo "Skipping RDS cluster '$DB_INSTANCE': status '$db_status'."
            ;;
        esac
        ;;
      *)
        echo "Skipping RDS stop: '$DB_INSTANCE' was not found as an instance or cluster in region '$REGION'."
        ;;
    esac
  fi
fi

echo
echo "Pause complete."
echo "Note: ALB/CloudFront still incur low baseline cost."
echo "Resume with: scripts/aws/resume_stack.sh --region $REGION"

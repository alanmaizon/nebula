#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/aws/resume_stack.sh [options]

Resume Nebula AWS runtime by starting RDS and scaling ECS services back up.

Options:
  --profile PROFILE            AWS profile (optional)
  --region REGION              AWS region (default: $AWS_REGION or eu-central-1)
  --cluster NAME               ECS cluster name (default: $ECS_CLUSTER or nebula-cluster)
  --backend-service NAME       Backend ECS service name (default: $ECS_BACKEND_SERVICE or nebula-backend)
  --backend-container NAME     Backend container name (default: $ECS_BACKEND_CONTAINER_NAME or backend service)
  --frontend-service NAME      Frontend ECS service name (default: $ECS_FRONTEND_SERVICE or nebula-frontend)
  --db-instance NAME           RDS DB identifier (instance or cluster; default: $DB_INSTANCE_ID)
  --backend-count N            Backend desired count (default: 1)
  --frontend-count N           Frontend desired count (default: 1)
  --skip-db                    Skip the RDS start step
  -h, --help                   Show help
USAGE
}

PROFILE="${AWS_PROFILE:-}"
REGION="${AWS_REGION:-eu-central-1}"
CLUSTER="${ECS_CLUSTER:-nebula-cluster}"
BACKEND_SERVICE="${ECS_BACKEND_SERVICE:-nebula-backend}"
BACKEND_CONTAINER="${ECS_BACKEND_CONTAINER_NAME:-}"
FRONTEND_SERVICE="${ECS_FRONTEND_SERVICE:-nebula-frontend}"
DB_INSTANCE="${DB_INSTANCE_ID:-}"
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
    --backend-container)
      BACKEND_CONTAINER="$2"
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

AWS_CMD=(aws --region "$REGION")
if [[ -n "$PROFILE" ]]; then
  AWS_CMD+=(--profile "$PROFILE")
fi

if [[ -z "$BACKEND_CONTAINER" ]]; then
  BACKEND_CONTAINER="$BACKEND_SERVICE"
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

container_env_value() {
  local task_def_json="$1"
  local key="$2"
  echo "$task_def_json" | jq -r --arg NAME "$BACKEND_CONTAINER" --arg KEY "$key" '
    [
      .taskDefinition.containerDefinitions[]
      | select(.name == $NAME)
      | .environment[]?
      | select(.name == $KEY)
      | .value
    ]
    | last // empty
  '
}

container_secret_ref() {
  local task_def_json="$1"
  local key="$2"
  echo "$task_def_json" | jq -r --arg NAME "$BACKEND_CONTAINER" --arg KEY "$key" '
    [
      .taskDefinition.containerDefinitions[]
      | select(.name == $NAME)
      | .secrets[]?
      | select(.name == $KEY)
      | .valueFrom
    ]
    | last // empty
  '
}

resolve_secrets_manager_value() {
  local value_from="$1"
  local secret_id="$value_from"
  local json_key=""

  if [[ "$value_from" == arn:aws:secretsmanager:* ]]; then
    IFS=':' read -r -a parts <<< "$value_from"
    if [[ ${#parts[@]} -ge 7 ]]; then
      secret_id="${parts[0]}:${parts[1]}:${parts[2]}:${parts[3]}:${parts[4]}:${parts[5]}:${parts[6]}"
      if [[ ${#parts[@]} -ge 8 ]]; then
        json_key="${parts[7]}"
      fi
    fi
  fi

  local secret_payload
  secret_payload="$(aws_json secretsmanager get-secret-value --secret-id "$secret_id" --output json)"
  local secret_string
  secret_string="$(echo "$secret_payload" | jq -r '.SecretString // empty')"
  if [[ -z "$secret_string" ]]; then
    return 1
  fi

  if [[ -n "$json_key" ]]; then
    echo "$secret_string" | jq -r --arg KEY "$json_key" '.[$KEY] // empty'
    return 0
  fi

  if echo "$secret_string" | jq -e '.' >/dev/null 2>&1; then
    local json_guess
    json_guess="$(echo "$secret_string" | jq -r '.DATABASE_URL // .database_url // .url // empty')"
    if [[ -n "$json_guess" ]]; then
      echo "$json_guess"
      return 0
    fi
  fi

  echo "$secret_string"
}

resolve_ssm_value() {
  local value_from="$1"
  aws_json ssm get-parameter --name "$value_from" --with-decryption --output json \
    | jq -r '.Parameter.Value // empty'
}

resolve_value_from_ref() {
  local value_from="$1"
  if [[ "$value_from" == arn:aws:secretsmanager:* ]]; then
    resolve_secrets_manager_value "$value_from"
    return
  fi
  if [[ "$value_from" == arn:aws:ssm:* || "$value_from" == /* ]]; then
    resolve_ssm_value "$value_from"
    return
  fi
  return 1
}

resolve_database_url_from_ecs() {
  local task_def_arn
  task_def_arn="$(aws_json ecs describe-services \
    --cluster "$CLUSTER" \
    --services "$BACKEND_SERVICE" \
    --query 'services[0].taskDefinition' \
    --output text 2>/dev/null || true)"
  if [[ -z "$task_def_arn" || "$task_def_arn" == "None" ]]; then
    return 1
  fi

  local task_def_json
  task_def_json="$(aws_json ecs describe-task-definition --task-definition "$task_def_arn" --output json)"
  local direct_value
  direct_value="$(container_env_value "$task_def_json" "DATABASE_URL")"
  if [[ -n "$direct_value" ]]; then
    echo "$direct_value"
    return 0
  fi

  local secret_ref
  secret_ref="$(container_secret_ref "$task_def_json" "DATABASE_URL")"
  if [[ -n "$secret_ref" ]]; then
    resolve_value_from_ref "$secret_ref"
    return
  fi

  return 1
}

extract_host_from_database_url() {
  local url="$1"
  python3 -c 'import sys; from urllib.parse import urlparse; print(urlparse(sys.argv[1]).hostname or "")' "$url"
}

find_db_instance_by_host() {
  local host="$1"
  aws_json rds describe-db-instances --output json \
    | jq -r --arg HOST "$host" '
        .DBInstances[]
        | select(.Endpoint.Address == $HOST)
        | .DBInstanceIdentifier
      ' \
    | head -n1
}

resolve_db_identifier() {
  if [[ -n "$DB_INSTANCE" ]]; then
    echo "$DB_INSTANCE"
    return 0
  fi

  local database_url
  database_url="$(resolve_database_url_from_ecs || true)"
  if [[ "$database_url" != postgresql://* && "$database_url" != postgres://* ]]; then
    return 1
  fi

  local db_host
  db_host="$(extract_host_from_database_url "$database_url")"
  if [[ -z "$db_host" ]]; then
    return 1
  fi

  find_db_instance_by_host "$db_host"
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

wait_for_cluster_available() {
  local identifier="$1"
  local timeout_seconds=900
  local sleep_seconds=15
  local deadline="$(( $(date +%s) + timeout_seconds ))"

  while true; do
    local status
    status="$(aws_json rds describe-db-clusters \
      --db-cluster-identifier "$identifier" \
      --query 'DBClusters[0].Status' \
      --output text 2>/dev/null || true)"
    if [[ "$status" == "available" ]]; then
      return 0
    fi
    if (( "$(date +%s)" >= deadline )); then
      echo "Timed out waiting for DB cluster '$identifier' to become available (last status: $status)." >&2
      return 1
    fi
    sleep "$sleep_seconds"
  done
}

wait_for_services() {
  local timeout_seconds=600
  local sleep_seconds=15
  local deadline="$(( $(date +%s) + timeout_seconds ))"

  while true; do
    local describe_json
    describe_json="$(aws_json ecs describe-services \
      --cluster "$CLUSTER" \
      --services "${UPDATED_SERVICES[@]}" \
      --output json)"

    echo "Current ECS rollout status:"
    echo "${describe_json}" | jq -r '
      .services[]
      | "\(.serviceName): desired=\(.desiredCount) running=\(.runningCount) pending=\(.pendingCount) deployments=\([.deployments[] | "\(.status):\(.rolloutState // "n/a"):\(.runningCount)"] | join(","))"
    '

    local all_stable=true
    for svc in "${UPDATED_SERVICES[@]}"; do
      local stable
      stable="$(echo "${describe_json}" | jq -r --arg svc "${svc}" '
        .services[]
        | select(.serviceName == $svc)
        | (
            .runningCount == .desiredCount
            and .pendingCount == 0
            and (.deployments | length) == 1
            and (.deployments[0].status == "PRIMARY")
            and ((.deployments[0].rolloutState // "COMPLETED") == "COMPLETED")
          )
      ')"
      if [[ "${stable}" != "true" ]]; then
        all_stable=false
      fi
    done

    if [[ "${all_stable}" == "true" ]]; then
      return 0
    fi

    if (( "$(date +%s)" >= deadline )); then
      echo "Timed out waiting for ECS services to stabilize after ${timeout_seconds}s."
      echo "Recent service diagnostics:"
      echo "${describe_json}" | jq '
        .services[]
        | {
            serviceName,
            desiredCount,
            runningCount,
            pendingCount,
            deployments: [.deployments[] | {status, rolloutState, runningCount, pendingCount, taskDefinition}],
            events: [.events[0:10][] | {createdAt, message}]
          }
      '
      return 1
    fi

    sleep "${sleep_seconds}"
  done
}

if [[ "$SKIP_DB" -eq 0 ]]; then
  DB_INSTANCE="$(resolve_db_identifier || true)"
  if [[ -z "$DB_INSTANCE" ]]; then
    echo "ERROR: Could not resolve the RDS identifier. Set DB_INSTANCE_ID or pass --db-instance." >&2
    exit 1
  fi

  DB_KIND="$(detect_db_kind "$DB_INSTANCE" || true)"
  case "$DB_KIND" in
    instance)
      db_status="$(aws_json rds describe-db-instances \
        --db-instance-identifier "$DB_INSTANCE" \
        --query 'DBInstances[0].DBInstanceStatus' \
        --output text 2>/dev/null || true)"
      case "$db_status" in
        available)
          echo "RDS instance '$DB_INSTANCE' already available."
          ;;
        stopped)
          echo "Starting RDS instance '$DB_INSTANCE'..."
          aws_json rds start-db-instance \
            --db-instance-identifier "$DB_INSTANCE" >/dev/null
          echo "Waiting for RDS instance '$DB_INSTANCE' to become available..."
          aws_json rds wait db-instance-available \
            --db-instance-identifier "$DB_INSTANCE"
          ;;
        starting)
          echo "RDS instance '$DB_INSTANCE' is already starting. Waiting for availability..."
          aws_json rds wait db-instance-available \
            --db-instance-identifier "$DB_INSTANCE"
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
          echo "RDS cluster '$DB_INSTANCE' already available."
          ;;
        stopped)
          echo "Starting RDS cluster '$DB_INSTANCE'..."
          aws_json rds start-db-cluster \
            --db-cluster-identifier "$DB_INSTANCE" >/dev/null
          echo "Waiting for RDS cluster '$DB_INSTANCE' to become available..."
          wait_for_cluster_available "$DB_INSTANCE"
          ;;
        starting)
          echo "RDS cluster '$DB_INSTANCE' is already starting. Waiting for availability..."
          wait_for_cluster_available "$DB_INSTANCE"
          ;;
        *)
          echo "Skipping RDS cluster '$DB_INSTANCE': status '$db_status'."
          ;;
      esac
      ;;
    *)
      echo "ERROR: RDS identifier '$DB_INSTANCE' was not found as an instance or cluster in region '$REGION'." >&2
      exit 1
      ;;
  esac
fi

UPDATED_SERVICES=()

if service_is_active "$BACKEND_SERVICE"; then
  echo "Scaling ECS service '$BACKEND_SERVICE' to $BACKEND_COUNT..."
  aws_json ecs update-service \
    --cluster "$CLUSTER" \
    --service "$BACKEND_SERVICE" \
    --desired-count "$BACKEND_COUNT" >/dev/null
  UPDATED_SERVICES+=("$BACKEND_SERVICE")
else
  echo "Skipping backend service '$BACKEND_SERVICE' (not found or not ACTIVE)."
fi

if [[ -n "$FRONTEND_SERVICE" ]] && service_is_active "$FRONTEND_SERVICE"; then
  echo "Scaling ECS service '$FRONTEND_SERVICE' to $FRONTEND_COUNT..."
  aws_json ecs update-service \
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
  wait_for_services
fi

echo
echo "Resume complete."
echo "If UI looks stale, run CloudFront invalidation for '/' and '/_next/static/*'."

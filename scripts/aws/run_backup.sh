#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/aws/run_backup.sh [options]

Create a Nebula AWS backup by snapshotting RDS and copying the uploads prefix.

Options:
  --profile PROFILE               AWS profile (optional)
  --region REGION                 AWS region (default: $AWS_REGION or eu-central-1)
  --cluster NAME                  ECS cluster name
  --backend-service NAME          ECS backend service name
  --backend-container NAME        Backend container name (default: backend service name)
  --db-instance NAME              RDS DB instance identifier override (optional)
  --backup-bucket NAME            S3 bucket to receive upload snapshots (default: app bucket)
  --backup-prefix PREFIX          S3 prefix for upload snapshots (default: nebula-backups)
  --retention-days N              Minimum RDS automated backup retention days (default: 7)
  --stop-db-after-backup BOOL     Stop the DB again if this script had to start it (default: true)
  --enable-s3-versioning BOOL     Ensure the uploads bucket has versioning enabled (default: true)
  --copy-s3-snapshot BOOL         Copy uploads prefix into backup prefix (default: true)
  -h, --help                      Show help

Environment fallbacks:
  AWS_REGION, AWS_PROFILE, ECS_CLUSTER, ECS_BACKEND_SERVICE, ECS_BACKEND_CONTAINER_NAME,
  DB_INSTANCE_ID, BACKUP_S3_BUCKET, BACKUP_S3_PREFIX, RDS_BACKUP_RETENTION_DAYS,
  STOP_DB_AFTER_BACKUP, ENABLE_S3_VERSIONING, COPY_S3_SNAPSHOT
USAGE
}

PROFILE="${AWS_PROFILE:-}"
REGION="${AWS_REGION:-eu-central-1}"
CLUSTER="${ECS_CLUSTER:-}"
BACKEND_SERVICE="${ECS_BACKEND_SERVICE:-}"
BACKEND_CONTAINER="${ECS_BACKEND_CONTAINER_NAME:-}"
DB_INSTANCE="${DB_INSTANCE_ID:-}"
BACKUP_BUCKET="${BACKUP_S3_BUCKET:-}"
BACKUP_PREFIX="${BACKUP_S3_PREFIX:-nebula-backups}"
RETENTION_DAYS="${RDS_BACKUP_RETENTION_DAYS:-7}"
STOP_DB_AFTER_BACKUP="${STOP_DB_AFTER_BACKUP:-true}"
ENABLE_S3_VERSIONING="${ENABLE_S3_VERSIONING:-true}"
COPY_S3_SNAPSHOT="${COPY_S3_SNAPSHOT:-true}"

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
    --db-instance)
      DB_INSTANCE="$2"
      shift 2
      ;;
    --backup-bucket)
      BACKUP_BUCKET="$2"
      shift 2
      ;;
    --backup-prefix)
      BACKUP_PREFIX="$2"
      shift 2
      ;;
    --retention-days)
      RETENTION_DAYS="$2"
      shift 2
      ;;
    --stop-db-after-backup)
      STOP_DB_AFTER_BACKUP="$2"
      shift 2
      ;;
    --enable-s3-versioning)
      ENABLE_S3_VERSIONING="$2"
      shift 2
      ;;
    --copy-s3-snapshot)
      COPY_S3_SNAPSHOT="$2"
      shift 2
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

if [[ -z "$CLUSTER" || -z "$BACKEND_SERVICE" ]]; then
  echo "ERROR: --cluster and --backend-service are required." >&2
  exit 1
fi

if [[ -z "$BACKEND_CONTAINER" ]]; then
  BACKEND_CONTAINER="$BACKEND_SERVICE"
fi

AWS_CMD=(aws --region "$REGION")
if [[ -n "$PROFILE" ]]; then
  AWS_CMD+=(--profile "$PROFILE")
fi

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SNAPSHOT_ID=""
S3_SNAPSHOT_URI=""
S3_VERSIONING_STATUS="unknown"
STORAGE_BACKEND=""
DB_STATUS=""
DB_STARTED_FOR_BACKUP=0
ORIGINAL_DB_STATUS=""

info() {
  echo "INFO: $1"
}

warn() {
  echo "WARN: $1"
}

fail() {
  echo "ERROR: $1" >&2
  exit 1
}

bool_is_true() {
  local value
  value="$(echo "${1:-false}" | tr '[:upper:]' '[:lower:]')"
  [[ "$value" == "1" || "$value" == "true" || "$value" == "yes" || "$value" == "y" ]]
}

aws_json() {
  "${AWS_CMD[@]}" "$@"
}

append_summary() {
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    printf '%s\n' "$1" >> "$GITHUB_STEP_SUMMARY"
  fi
}

cleanup() {
  local exit_code=$?
  if [[ "$DB_STARTED_FOR_BACKUP" -eq 1 ]] && bool_is_true "$STOP_DB_AFTER_BACKUP"; then
    info "Stopping RDS instance '$DB_INSTANCE' to restore the pre-backup state..."
    if aws_json rds stop-db-instance --db-instance-identifier "$DB_INSTANCE" >/dev/null 2>&1; then
      aws_json rds wait db-instance-stopped --db-instance-identifier "$DB_INSTANCE" || true
    else
      warn "Unable to stop RDS instance '$DB_INSTANCE' after backup."
    fi
  fi
  exit "$exit_code"
}

trap cleanup EXIT

container_env_value() {
  local key="$1"
  echo "$TASK_DEF_JSON" | jq -r --arg NAME "$BACKEND_CONTAINER" --arg KEY "$key" '
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
  local key="$1"
  echo "$TASK_DEF_JSON" | jq -r --arg NAME "$BACKEND_CONTAINER" --arg KEY "$key" '
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

extract_host_from_database_url() {
  local url="$1"
  python3 -c 'import sys; from urllib.parse import urlparse; print(urlparse(sys.argv[1]).hostname or "")' "$url"
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
    fail "Secret '$secret_id' has no SecretString payload."
  fi

  if [[ -n "$json_key" ]]; then
    echo "$secret_string" | jq -r --arg KEY "$json_key" '.[$KEY] // empty'
    return
  fi

  if echo "$secret_string" | jq -e '.' >/dev/null 2>&1; then
    local json_guess
    json_guess="$(echo "$secret_string" | jq -r '.DATABASE_URL // .database_url // .url // empty')"
    if [[ -n "$json_guess" ]]; then
      echo "$json_guess"
      return
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
  fail "Unsupported secret reference format: '$value_from'"
}

resolve_config_value() {
  local key="$1"
  local fallback="${2:-}"
  local direct_value
  direct_value="$(container_env_value "$key")"
  if [[ -n "$direct_value" ]]; then
    echo "$direct_value"
    return
  fi

  local secret_ref
  secret_ref="$(container_secret_ref "$key")"
  if [[ -n "$secret_ref" ]]; then
    resolve_value_from_ref "$secret_ref"
    return
  fi

  echo "$fallback"
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

info "Checking AWS identity..."
aws_json sts get-caller-identity >/dev/null

info "Resolving ECS backend task definition..."
TASK_DEF_ARN="$(aws_json ecs describe-services \
  --cluster "$CLUSTER" \
  --services "$BACKEND_SERVICE" \
  --query 'services[0].taskDefinition' \
  --output text)"

if [[ -z "$TASK_DEF_ARN" || "$TASK_DEF_ARN" == "None" ]]; then
  fail "Unable to resolve task definition for ECS service '$BACKEND_SERVICE'."
fi

TASK_DEF_JSON="$(aws_json ecs describe-task-definition --task-definition "$TASK_DEF_ARN" --output json)"

if ! echo "$TASK_DEF_JSON" | jq -e --arg NAME "$BACKEND_CONTAINER" '
  .taskDefinition.containerDefinitions[] | select(.name == $NAME)
' >/dev/null; then
  fail "Container '$BACKEND_CONTAINER' not found in task definition '$TASK_DEF_ARN'."
fi

STORAGE_BACKEND="$(resolve_config_value "STORAGE_BACKEND" "local")"
S3_BUCKET_VALUE="$(resolve_config_value "S3_BUCKET" "")"
S3_PREFIX_VALUE="$(resolve_config_value "S3_PREFIX" "nebula")"

if [[ -z "$DB_INSTANCE" ]]; then
  DATABASE_URL="$(resolve_config_value "DATABASE_URL" "")"
  if [[ "$DATABASE_URL" == postgresql://* || "$DATABASE_URL" == postgres://* ]]; then
    DB_HOST="$(extract_host_from_database_url "$DATABASE_URL")"
    if [[ -n "$DB_HOST" ]]; then
      DB_INSTANCE="$(find_db_instance_by_host "$DB_HOST")"
      if [[ -n "$DB_INSTANCE" ]]; then
        info "Resolved RDS instance '$DB_INSTANCE' from DATABASE_URL host '$DB_HOST'."
      fi
    fi
  fi
fi

if [[ -z "$DB_INSTANCE" ]]; then
  if aws_json rds describe-db-instances --db-instance-identifier nebula-postgres >/dev/null 2>&1; then
    DB_INSTANCE="nebula-postgres"
    info "Falling back to the default RDS instance identifier '$DB_INSTANCE'."
  fi
fi

if [[ -n "$DB_INSTANCE" ]]; then
  ORIGINAL_DB_STATUS="$(aws_json rds describe-db-instances \
    --db-instance-identifier "$DB_INSTANCE" \
    --query 'DBInstances[0].DBInstanceStatus' \
    --output text)"
  DB_STATUS="$ORIGINAL_DB_STATUS"

  if [[ "$DB_STATUS" == "stopped" ]]; then
    info "Starting stopped RDS instance '$DB_INSTANCE' for backup..."
    aws_json rds start-db-instance --db-instance-identifier "$DB_INSTANCE" >/dev/null
    aws_json rds wait db-instance-available --db-instance-identifier "$DB_INSTANCE"
    DB_STATUS="available"
    DB_STARTED_FOR_BACKUP=1
  elif [[ "$DB_STATUS" == "starting" ]]; then
    info "Waiting for RDS instance '$DB_INSTANCE' to become available..."
    aws_json rds wait db-instance-available --db-instance-identifier "$DB_INSTANCE"
    DB_STATUS="available"
  fi

  CURRENT_RETENTION="$(aws_json rds describe-db-instances \
    --db-instance-identifier "$DB_INSTANCE" \
    --query 'DBInstances[0].BackupRetentionPeriod' \
    --output text)"
  if [[ "$CURRENT_RETENTION" -lt "$RETENTION_DAYS" ]]; then
    info "Updating RDS automated backup retention from $CURRENT_RETENTION to $RETENTION_DAYS day(s)..."
    aws_json rds modify-db-instance \
      --db-instance-identifier "$DB_INSTANCE" \
      --backup-retention-period "$RETENTION_DAYS" \
      --apply-immediately >/dev/null
    aws_json rds wait db-instance-available --db-instance-identifier "$DB_INSTANCE"
  else
    info "RDS automated backup retention is already $CURRENT_RETENTION day(s)."
  fi

  SNAPSHOT_ID="${DB_INSTANCE}-manual-${TIMESTAMP,,}"
  info "Creating manual RDS snapshot '$SNAPSHOT_ID'..."
  aws_json rds create-db-snapshot \
    --db-instance-identifier "$DB_INSTANCE" \
    --db-snapshot-identifier "$SNAPSHOT_ID" >/dev/null
  aws_json rds wait db-snapshot-available --db-snapshot-identifier "$SNAPSHOT_ID"
else
  warn "No RDS instance identifier was resolved. Set DB_INSTANCE_ID if you want database snapshots."
fi

if [[ "$STORAGE_BACKEND" == "s3" ]]; then
  if [[ -z "$S3_BUCKET_VALUE" ]]; then
    fail "STORAGE_BACKEND=s3 but S3_BUCKET is empty."
  fi

  if bool_is_true "$ENABLE_S3_VERSIONING"; then
    S3_VERSIONING_STATUS="$(aws_json s3api get-bucket-versioning --bucket "$S3_BUCKET_VALUE" --output json \
      | jq -r '.Status // "Disabled"')"
    if [[ "$S3_VERSIONING_STATUS" != "Enabled" ]]; then
      info "Enabling versioning on bucket '$S3_BUCKET_VALUE'..."
      aws_json s3api put-bucket-versioning \
        --bucket "$S3_BUCKET_VALUE" \
        --versioning-configuration Status=Enabled
      S3_VERSIONING_STATUS="Enabled"
    else
      info "S3 bucket '$S3_BUCKET_VALUE' already has versioning enabled."
    fi
  fi

  if bool_is_true "$COPY_S3_SNAPSHOT"; then
    if [[ -z "$BACKUP_BUCKET" ]]; then
      BACKUP_BUCKET="$S3_BUCKET_VALUE"
    fi
    BACKUP_PREFIX="${BACKUP_PREFIX%/}"
    if [[ -n "$S3_PREFIX_VALUE" ]]; then
      SOURCE_PREFIX="${S3_PREFIX_VALUE%/}/uploads"
    else
      SOURCE_PREFIX="uploads"
    fi
    TARGET_PREFIX="${BACKUP_PREFIX}/uploads/${TIMESTAMP}"
    S3_SNAPSHOT_URI="s3://${BACKUP_BUCKET}/${TARGET_PREFIX}"

    info "Copying uploads snapshot from s3://${S3_BUCKET_VALUE}/${SOURCE_PREFIX} to ${S3_SNAPSHOT_URI}..."
    aws s3 sync \
      "s3://${S3_BUCKET_VALUE}/${SOURCE_PREFIX}" \
      "${S3_SNAPSHOT_URI}" \
      --region "$REGION" \
      ${PROFILE:+--profile "$PROFILE"} \
      --only-show-errors
  fi
else
  warn "STORAGE_BACKEND='$STORAGE_BACKEND'; upload backups are skipped because ECS local storage is not durable."
fi

echo
echo "Backup complete."
if [[ -n "$SNAPSHOT_ID" ]]; then
  echo "RDS snapshot: $SNAPSHOT_ID"
fi
if [[ -n "$S3_SNAPSHOT_URI" ]]; then
  echo "S3 snapshot: $S3_SNAPSHOT_URI"
fi
if [[ "$STORAGE_BACKEND" == "s3" ]]; then
  echo "S3 versioning: $S3_VERSIONING_STATUS"
fi

append_summary "## AWS Backup"
append_summary "- Timestamp: \`$TIMESTAMP\`"
append_summary "- ECS cluster: \`$CLUSTER\`"
append_summary "- Backend service: \`$BACKEND_SERVICE\`"
if [[ -n "$DB_INSTANCE" ]]; then
  append_summary "- RDS instance: \`$DB_INSTANCE\`"
fi
if [[ -n "$SNAPSHOT_ID" ]]; then
  append_summary "- RDS snapshot: \`$SNAPSHOT_ID\`"
fi
append_summary "- Storage backend: \`$STORAGE_BACKEND\`"
if [[ -n "$S3_SNAPSHOT_URI" ]]; then
  append_summary "- Upload snapshot: \`$S3_SNAPSHOT_URI\`"
fi

#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/aws/check_deploy_readiness.sh [options]

Checks AWS deployment readiness for Nebula ECS/ECR pipeline.

Options:
  --region REGION                  AWS region (default: $AWS_REGION)
  --profile PROFILE                AWS profile (optional)
  --cluster NAME                   ECS cluster name
  --backend-service NAME           ECS backend service name
  --backend-container NAME         Backend container name (optional; defaults to backend service)
  --backend-repo NAME              ECR backend repository
  --frontend-service NAME          ECS frontend service name (optional)
  --frontend-container NAME        Frontend container name (optional; defaults to frontend service)
  --frontend-repo NAME             ECR frontend repository (optional)
  --frontend-api-base VALUE        Frontend API base (default: $NEXT_PUBLIC_API_BASE)
  --role-arn ARN                   GitHub deploy IAM role ARN (optional)
  --required-backend-vars CSV      Required backend env/secrets names

Environment fallbacks:
  AWS_REGION, AWS_PROFILE, ECS_CLUSTER, ECS_BACKEND_SERVICE, ECS_BACKEND_CONTAINER_NAME,
  ECR_BACKEND_REPOSITORY, ECS_FRONTEND_SERVICE, ECS_FRONTEND_CONTAINER_NAME,
  ECR_FRONTEND_REPOSITORY, NEXT_PUBLIC_API_BASE, AWS_ROLE_TO_ASSUME, REQUIRED_BACKEND_VARS
USAGE
}

REGION="${AWS_REGION:-}"
PROFILE="${AWS_PROFILE:-}"
CLUSTER="${ECS_CLUSTER:-}"
BACKEND_SERVICE="${ECS_BACKEND_SERVICE:-}"
BACKEND_CONTAINER="${ECS_BACKEND_CONTAINER_NAME:-}"
BACKEND_REPO="${ECR_BACKEND_REPOSITORY:-}"
FRONTEND_SERVICE="${ECS_FRONTEND_SERVICE:-}"
FRONTEND_CONTAINER="${ECS_FRONTEND_CONTAINER_NAME:-}"
FRONTEND_REPO="${ECR_FRONTEND_REPOSITORY:-}"
FRONTEND_API_BASE="${NEXT_PUBLIC_API_BASE:-}"
ROLE_ARN="${AWS_ROLE_TO_ASSUME:-}"
REQUIRED_BACKEND_VARS="${REQUIRED_BACKEND_VARS:-APP_ENV,AWS_REGION,BEDROCK_MODEL_ID,BEDROCK_LITE_MODEL_ID,BEDROCK_EMBEDDING_MODEL_ID,DATABASE_URL,STORAGE_BACKEND,S3_BUCKET,S3_PREFIX,STORAGE_ROOT,CORS_ORIGINS}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)
      REGION="$2"
      shift 2
      ;;
    --profile)
      PROFILE="$2"
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
    --backend-repo)
      BACKEND_REPO="$2"
      shift 2
      ;;
    --frontend-service)
      FRONTEND_SERVICE="$2"
      shift 2
      ;;
    --frontend-container)
      FRONTEND_CONTAINER="$2"
      shift 2
      ;;
    --frontend-repo)
      FRONTEND_REPO="$2"
      shift 2
      ;;
    --frontend-api-base)
      FRONTEND_API_BASE="$2"
      shift 2
      ;;
    --role-arn)
      ROLE_ARN="$2"
      shift 2
      ;;
    --required-backend-vars)
      REQUIRED_BACKEND_VARS="$2"
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

if [[ -z "$REGION" ]]; then
  echo "ERROR: --region or AWS_REGION is required." >&2
  exit 1
fi
if [[ -z "$CLUSTER" || -z "$BACKEND_SERVICE" || -z "$BACKEND_REPO" ]]; then
  echo "ERROR: cluster/backend-service/backend-repo are required." >&2
  exit 1
fi

if [[ -z "$BACKEND_CONTAINER" ]]; then
  BACKEND_CONTAINER="$BACKEND_SERVICE"
fi
if [[ -n "$FRONTEND_SERVICE" && -z "$FRONTEND_CONTAINER" ]]; then
  FRONTEND_CONTAINER="$FRONTEND_SERVICE"
fi

AWS_CMD=(aws --region "$REGION")
if [[ -n "$PROFILE" ]]; then
  AWS_CMD+=(--profile "$PROFILE")
fi

failures=()
warnings=()

pass() {
  echo "PASS: $1"
}

fail() {
  failures+=("$1")
  echo "FAIL: $1"
}

warn() {
  warnings+=("$1")
  echo "WARN: $1"
}

aws_json() {
  "${AWS_CMD[@]}" "$@"
}

identity_json=""
if identity_json="$(aws_json sts get-caller-identity --output json 2>/dev/null)"; then
  account_id="$(echo "$identity_json" | jq -r '.Account')"
  arn="$(echo "$identity_json" | jq -r '.Arn')"
  pass "AWS identity resolved (account=$account_id, arn=$arn)"
else
  fail "Unable to resolve AWS identity with current credentials/profile"
fi

oidc_arns=""
if oidc_arns="$(aws_json iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[].Arn' --output text 2>/dev/null)"; then
  if echo "$oidc_arns" | tr '\t' '\n' | grep -q 'oidc-provider/token.actions.githubusercontent.com'; then
    pass "GitHub OIDC provider exists"
  else
    fail "Missing IAM OIDC provider for token.actions.githubusercontent.com"
  fi
else
  fail "Unable to query IAM OIDC providers"
fi

if [[ -n "$ROLE_ARN" ]]; then
  role_name="${ROLE_ARN##*/}"
  role_json=""
  if role_json="$(aws_json iam get-role --role-name "$role_name" --output json 2>/dev/null)"; then
    if echo "$role_json" | jq -e '
      .Role.AssumeRolePolicyDocument.Statement[]
      | select(
          ((.Principal.Federated // "") | tostring | test("token.actions.githubusercontent.com"))
          and
          ((.Action | tostring) | test("AssumeRoleWithWebIdentity"))
        )
    ' >/dev/null; then
      pass "Deploy role trust policy supports GitHub OIDC (${role_name})"
    else
      fail "Deploy role trust policy does not allow GitHub OIDC web identity (${role_name})"
    fi
  else
    fail "Deploy role not found or not readable (${role_name})"
  fi
else
  warn "AWS_ROLE_TO_ASSUME/--role-arn not provided; skipping deploy role trust validation"
fi

if aws_json ecr describe-repositories --repository-names "$BACKEND_REPO" --output json >/dev/null 2>&1; then
  pass "Backend ECR repository exists (${BACKEND_REPO})"
else
  fail "Backend ECR repository missing (${BACKEND_REPO})"
fi

if [[ -n "$FRONTEND_REPO" ]]; then
  if aws_json ecr describe-repositories --repository-names "$FRONTEND_REPO" --output json >/dev/null 2>&1; then
    pass "Frontend ECR repository exists (${FRONTEND_REPO})"
  else
    fail "Frontend ECR repository missing (${FRONTEND_REPO})"
  fi
fi

cluster_status="$(aws_json ecs describe-clusters --clusters "$CLUSTER" --query 'clusters[0].status' --output text 2>/dev/null || true)"
if [[ "$cluster_status" == "ACTIVE" ]]; then
  pass "ECS cluster is active (${CLUSTER})"
else
  fail "ECS cluster not found/active (${CLUSTER})"
fi

check_service() {
  local service_name="$1"
  local container_name="$2"
  local required_csv="$3"

  local service_status
  service_status="$(aws_json ecs describe-services --cluster "$CLUSTER" --services "$service_name" --query 'services[0].status' --output text 2>/dev/null || true)"
  if [[ "$service_status" != "ACTIVE" ]]; then
    fail "ECS service not found/active (${service_name})"
    return
  fi
  pass "ECS service is active (${service_name})"

  local task_def_arn
  task_def_arn="$(aws_json ecs describe-services --cluster "$CLUSTER" --services "$service_name" --query 'services[0].taskDefinition' --output text 2>/dev/null || true)"
  if [[ -z "$task_def_arn" || "$task_def_arn" == "None" ]]; then
    fail "Unable to resolve task definition for service (${service_name})"
    return
  fi

  local task_def_json
  task_def_json="$(aws_json ecs describe-task-definition --task-definition "$task_def_arn" --output json 2>/dev/null || true)"
  if [[ -z "$task_def_json" ]]; then
    fail "Unable to describe task definition (${task_def_arn})"
    return
  fi

  if ! echo "$task_def_json" | jq -e --arg NAME "$container_name" '.taskDefinition.containerDefinitions[] | select(.name == $NAME)' >/dev/null; then
    local available
    available="$(echo "$task_def_json" | jq -r '.taskDefinition.containerDefinitions[].name' | paste -sd ',' -)"
    fail "Container '${container_name}' not found in task definition (${task_def_arn}); available: ${available}"
    return
  fi

  local key_set
  key_set="$( (echo "$task_def_json" | jq -r --arg NAME "$container_name" '
      [
        (.taskDefinition.containerDefinitions[] | select(.name == $NAME) | .environment[]?.name),
        (.taskDefinition.containerDefinitions[] | select(.name == $NAME) | .secrets[]?.name)
      ]
      | flatten
      | unique
      | .[]
    ') || true )"
  local missing=()
  IFS=',' read -r -a required_keys <<< "$required_csv"
  for key in "${required_keys[@]}"; do
    key="${key// /}"
    [[ -z "$key" ]] && continue
    if ! echo "$key_set" | grep -qx "$key"; then
      missing+=("$key")
    fi
  done

  if [[ "${#missing[@]}" -eq 0 ]]; then
    pass "Container ${container_name} includes required env/secrets keys"
  else
    fail "Container ${container_name} missing required env/secrets keys: ${missing[*]}"
  fi

  local db_url
  db_url="$(echo "$task_def_json" | jq -r --arg NAME "$container_name" '
    (.taskDefinition.containerDefinitions[]
     | select(.name == $NAME)
     | (.environment[]? | select(.name == "DATABASE_URL") | .value)) // empty
  ')"
  local app_env
  app_env="$(echo "$task_def_json" | jq -r --arg NAME "$container_name" '
    (.taskDefinition.containerDefinitions[]
     | select(.name == $NAME)
     | (.environment[]? | select(.name == "APP_ENV") | .value)) // empty
  ')"
  local storage_backend
  storage_backend="$(echo "$task_def_json" | jq -r --arg NAME "$container_name" '
    (.taskDefinition.containerDefinitions[]
     | select(.name == $NAME)
     | (.environment[]? | select(.name == "STORAGE_BACKEND") | .value)) // empty
  ')"
  local s3_bucket
  s3_bucket="$(echo "$task_def_json" | jq -r --arg NAME "$container_name" '
    (.taskDefinition.containerDefinitions[]
     | select(.name == $NAME)
     | (.environment[]? | select(.name == "S3_BUCKET") | .value)) // empty
  ')"
  local cors_origins
  cors_origins="$(echo "$task_def_json" | jq -r --arg NAME "$container_name" '
    (.taskDefinition.containerDefinitions[]
     | select(.name == $NAME)
     | (.environment[]? | select(.name == "CORS_ORIGINS") | .value)) // empty
  ')"
  local auth_enabled
  auth_enabled="$(echo "$task_def_json" | jq -r --arg NAME "$container_name" '
    (.taskDefinition.containerDefinitions[]
     | select(.name == $NAME)
     | (.environment[]? | select(.name == "AUTH_ENABLED") | .value)) // empty
  ')"
  local cognito_region
  cognito_region="$(echo "$task_def_json" | jq -r --arg NAME "$container_name" '
    (.taskDefinition.containerDefinitions[]
     | select(.name == $NAME)
     | (.environment[]? | select(.name == "COGNITO_REGION") | .value)) // empty
  ')"
  local cognito_user_pool_id
  cognito_user_pool_id="$(echo "$task_def_json" | jq -r --arg NAME "$container_name" '
    (.taskDefinition.containerDefinitions[]
     | select(.name == $NAME)
     | (.environment[]? | select(.name == "COGNITO_USER_POOL_ID") | .value)) // empty
  ')"
  local cognito_app_client_id
  cognito_app_client_id="$(echo "$task_def_json" | jq -r --arg NAME "$container_name" '
    (.taskDefinition.containerDefinitions[]
     | select(.name == $NAME)
     | (.environment[]? | select(.name == "COGNITO_APP_CLIENT_ID") | .value)) // empty
  ')"
  local cognito_issuer
  cognito_issuer="$(echo "$task_def_json" | jq -r --arg NAME "$container_name" '
    (.taskDefinition.containerDefinitions[]
     | select(.name == $NAME)
     | (.environment[]? | select(.name == "COGNITO_ISSUER") | .value)) // empty
  ')"

  if [[ -n "$db_url" && "$db_url" == sqlite:* ]]; then
    if [[ "${app_env}" == "production" ]]; then
      fail "Container ${container_name} uses sqlite DATABASE_URL in production; configure RDS/Postgres"
    else
      warn "Container ${container_name} uses sqlite DATABASE_URL; use RDS/Postgres for production"
    fi
  fi

  if [[ "${app_env}" == "production" ]]; then
    if [[ -z "${storage_backend}" || "${storage_backend}" == "local" || "${storage_backend}" == "filesystem" || "${storage_backend}" == "fs" ]]; then
      fail "Container ${container_name} uses local STORAGE_BACKEND in production; configure S3 storage"
    fi
    if [[ -n "${cors_origins}" ]]; then
      if echo "${cors_origins}" | grep -q "http://"; then
        fail "Container ${container_name} has insecure CORS_ORIGINS in production (http:// not allowed): ${cors_origins}"
      fi
      if echo "${cors_origins}" | grep -Eqi "(^|,)[[:space:]]*\\*([[:space:]]*,|$)"; then
        fail "Container ${container_name} has wildcard CORS_ORIGINS in production: ${cors_origins}"
      fi
      if echo "${cors_origins}" | grep -Eqi "localhost|127\\.0\\.0\\.1"; then
        fail "Container ${container_name} has localhost CORS_ORIGINS in production: ${cors_origins}"
      fi
    fi

    local auth_enabled_lower
    auth_enabled_lower="$(echo "${auth_enabled:-}" | tr '[:upper:]' '[:lower:]')"
    if [[ "${auth_enabled_lower}" == "true" ]]; then
      if [[ -z "${cognito_app_client_id}" ]]; then
        fail "Container ${container_name} has AUTH_ENABLED=true in production but COGNITO_APP_CLIENT_ID is not set"
      fi
      if [[ -z "${cognito_issuer}" ]]; then
        if [[ -z "${cognito_region}" || -z "${cognito_user_pool_id}" ]]; then
          fail "Container ${container_name} has AUTH_ENABLED=true in production but Cognito issuer cannot be derived (set COGNITO_ISSUER or both COGNITO_REGION and COGNITO_USER_POOL_ID)"
        fi
      fi
    fi
  fi

  if [[ -n "${storage_backend}" && "${storage_backend}" == "s3" ]]; then
    if [[ -z "${s3_bucket}" ]]; then
      fail "Container ${container_name} has STORAGE_BACKEND=s3 but S3_BUCKET is not set"
    fi
  fi

  local app_aws_region
  app_aws_region="$(echo "$task_def_json" | jq -r --arg NAME "$container_name" '
    (.taskDefinition.containerDefinitions[]
     | select(.name == $NAME)
     | (.environment[]? | select(.name == "AWS_REGION") | .value)) // empty
  ')"
  local bedrock_model_id
  bedrock_model_id="$(echo "$task_def_json" | jq -r --arg NAME "$container_name" '
    (.taskDefinition.containerDefinitions[]
     | select(.name == $NAME)
     | (.environment[]? | select(.name == "BEDROCK_MODEL_ID") | .value)) // empty
  ')"
  local bedrock_lite_model_id
  bedrock_lite_model_id="$(echo "$task_def_json" | jq -r --arg NAME "$container_name" '
    (.taskDefinition.containerDefinitions[]
     | select(.name == $NAME)
     | (.environment[]? | select(.name == "BEDROCK_LITE_MODEL_ID") | .value)) // empty
  ')"

  if [[ -n "$app_aws_region" ]]; then
    for id in "$bedrock_model_id" "$bedrock_lite_model_id"; do
      [[ -z "$id" ]] && continue

      # If the identifier looks like a region-scoped inference profile (e.g. "<scope>.amazon.nova-..."),
      # ensure scope aligns with AWS_REGION to avoid "model identifier is invalid" failures.
      if [[ "$id" =~ ^([a-z]+)\.amazon\.nova- ]]; then
        local scope="${BASH_REMATCH[1]}"
        if [[ "$app_aws_region" == eu-* && "$scope" != "eu" && "$scope" != "global" ]]; then
          fail "Bedrock Nova identifier scope '${scope}.' does not match AWS_REGION='${app_aws_region}' for ${container_name}; use 'eu.' (or a foundation ID) for EU regions"
        fi
        if [[ "$app_aws_region" == us-* && "$scope" != "us" && "$scope" != "global" ]]; then
          fail "Bedrock Nova identifier scope '${scope}.' does not match AWS_REGION='${app_aws_region}' for ${container_name}; use 'us.' (or a foundation ID) for US regions"
        fi
      fi
    done

    # Bedrock may require inference profiles for Nova invocation in some regions/accounts even when
    # the foundation model identifier is valid.
    if [[ "$app_aws_region" == eu-* ]]; then
      if [[ "$bedrock_model_id" == amazon.nova-* || "$bedrock_lite_model_id" == amazon.nova-* ]]; then
        warn "Container ${container_name} uses Nova foundation IDs with AWS_REGION='${app_aws_region}'; if you hit 'on-demand throughput isn't supported', switch to EU inference profiles (eu.amazon.nova-pro-v1:0 / eu.amazon.nova-lite-v1:0)"
      fi
    fi
  fi
}

check_service "$BACKEND_SERVICE" "$BACKEND_CONTAINER" "$REQUIRED_BACKEND_VARS"

validate_frontend_api_base() {
  local raw="$1"
  local normalized="${raw%"${raw##*[![:space:]]}"}"
  normalized="${normalized#"${normalized%%[![:space:]]*}"}"

  if [[ -z "$normalized" ]]; then
    fail "NEXT_PUBLIC_API_BASE is required when frontend deployment is enabled"
    return
  fi

  if [[ "$normalized" == "/api" || "$normalized" == "/api/" ]]; then
    pass "NEXT_PUBLIC_API_BASE is configured for same-origin API routing (${normalized})"
    return
  fi

  if [[ "$normalized" == http://* ]]; then
    fail "NEXT_PUBLIC_API_BASE uses insecure http:// (${normalized}); use '/api' or an https:// URL"
    return
  fi

  if [[ "$normalized" == https://* ]]; then
    pass "NEXT_PUBLIC_API_BASE uses HTTPS origin (${normalized})"
    return
  fi

  fail "NEXT_PUBLIC_API_BASE has unsupported value '${normalized}'; use '/api' or an https:// URL"
}

if [[ -n "$FRONTEND_SERVICE" ]]; then
  check_service "$FRONTEND_SERVICE" "$FRONTEND_CONTAINER" "NEXT_PUBLIC_API_BASE"
  validate_frontend_api_base "$FRONTEND_API_BASE"
fi

echo ""
echo "Summary:"
echo "- failures: ${#failures[@]}"
echo "- warnings: ${#warnings[@]}"

if [[ "${#warnings[@]}" -gt 0 ]]; then
  printf '  WARN: %s\n' "${warnings[@]}"
fi

if [[ "${#failures[@]}" -gt 0 ]]; then
  printf '  FAIL: %s\n' "${failures[@]}"
  exit 1
fi

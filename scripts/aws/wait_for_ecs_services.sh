#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Wait for ECS services to become stable and print actionable diagnostics on failure.

Usage:
  bash scripts/aws/wait_for_ecs_services.sh --region REGION --cluster NAME --service NAME [--service NAME ...]

Options:
  --region REGION        AWS region (default: $AWS_REGION)
  --cluster NAME         ECS cluster name (default: $ECS_CLUSTER)
  --service NAME         ECS service name to monitor; may be repeated
  --timeout SECONDS      Overall timeout in seconds (default: 1800)
  --sleep SECONDS        Poll interval in seconds (default: 15)
EOF
}

REGION="${AWS_REGION:-}"
CLUSTER="${ECS_CLUSTER:-}"
TIMEOUT_SECONDS=1800
SLEEP_SECONDS=15
SERVICES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)
      REGION="$2"
      shift 2
      ;;
    --cluster)
      CLUSTER="$2"
      shift 2
      ;;
    --service)
      SERVICES+=("$2")
      shift 2
      ;;
    --timeout)
      TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --sleep)
      SLEEP_SECONDS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$REGION" || -z "$CLUSTER" || ${#SERVICES[@]} -eq 0 ]]; then
  echo "ERROR: --region, --cluster, and at least one --service are required." >&2
  usage >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required." >&2
  exit 1
fi

aws_json() {
  aws --region "$REGION" "$@"
}

service_status_lines() {
  local describe_json="$1"
  echo "$describe_json" | jq -r '
    .services[]
    | "\(.serviceName): desired=\(.desiredCount) running=\(.runningCount) pending=\(.pendingCount) deployments=\([.deployments[] | "\(.status):\(.rolloutState // "n/a"):\(.runningCount)"] | join(","))"
  '
}

service_is_stable() {
  local describe_json="$1"
  local service_name="$2"
  echo "$describe_json" | jq -e --arg svc "$service_name" '
    .services[]
    | select(.serviceName == $svc)
    | (
        .runningCount == .desiredCount
        and .pendingCount == 0
        and ([.deployments[] | select(.status == "PRIMARY")] | length) == 1
        and (([.deployments[] | select(.status == "PRIMARY")][0].rolloutState // "COMPLETED") == "COMPLETED")
        and (
          [
            .deployments[]
            | select(.status != "PRIMARY")
            | select(((.desiredCount // 0) > 0) or ((.runningCount // 0) > 0) or ((.pendingCount // 0) > 0))
          ] | length
        ) == 0
      )
  ' >/dev/null
}

recent_stopped_tasks_json() {
  local service_name="$1"
  local task_definition_arn="$2"

  local task_arns
  task_arns="$(aws_json ecs list-tasks \
    --cluster "$CLUSTER" \
    --service-name "$service_name" \
    --desired-status STOPPED \
    --max-items 5 \
    --query 'taskArns' \
    --output json 2>/dev/null || echo '[]')"

  if [[ "$(echo "$task_arns" | jq 'length')" -eq 0 ]]; then
    echo '{"tasks":[]}'
    return 0
  fi

  aws_json ecs describe-tasks \
    --cluster "$CLUSTER" \
    --tasks $(echo "$task_arns" | jq -r '.[]') \
    --output json \
  | jq --arg td "$task_definition_arn" '
      {
        tasks: [
          .tasks[]
          | select(.taskDefinitionArn == $td)
          | {
              taskArn,
              createdAt,
              startedAt,
              stoppedAt,
              stopCode,
              stoppedReason,
              containers: [
                .containers[]
                | {
                    name,
                    image,
                    lastStatus,
                    reason,
                    exitCode
                  }
              ]
            }
        ]
      }
    '
}

print_recent_log_excerpt() {
  local task_definition_arn="$1"
  local task_arn="$2"

  local taskdef_json
  taskdef_json="$(aws_json ecs describe-task-definition \
    --task-definition "$task_definition_arn" \
    --query 'taskDefinition.containerDefinitions' \
    --output json 2>/dev/null || echo '[]')"

  local log_group
  log_group="$(echo "$taskdef_json" | jq -r '
    [
      .[]
      | select((.logConfiguration.options["awslogs-group"] // "") != "")
      | .logConfiguration.options["awslogs-group"]
    ][0] // empty
  ')"
  local log_prefix
  log_prefix="$(echo "$taskdef_json" | jq -r '
    [
      .[]
      | select((.logConfiguration.options["awslogs-stream-prefix"] // "") != "")
      | .logConfiguration.options["awslogs-stream-prefix"]
    ][0] // empty
  ')"
  local container_name
  container_name="$(echo "$taskdef_json" | jq -r '
    [
      .[]
      | select((.logConfiguration.options["awslogs-group"] // "") != "")
      | .name
    ][0] // empty
  ')"

  if [[ -z "$log_group" || -z "$log_prefix" || -z "$container_name" ]]; then
    return 0
  fi

  local task_id="${task_arn##*/}"
  local log_stream="${log_prefix}/${container_name}/${task_id}"

  local log_events
  log_events="$(aws_json logs get-log-events \
    --log-group-name "$log_group" \
    --log-stream-name "$log_stream" \
    --limit 25 \
    --output json 2>/dev/null || true)"

  if [[ -z "$log_events" ]]; then
    return 0
  fi

  if [[ "$(echo "$log_events" | jq '.events | length')" -eq 0 ]]; then
    return 0
  fi

  echo "Recent container log excerpt:"
  echo "$log_events" | jq -r '.events[] | .message'
}

print_service_diagnostics() {
  local describe_json="$1"
  local service_name="$2"

  local service_json
  service_json="$(echo "$describe_json" | jq --arg svc "$service_name" '
    .services[]
    | select(.serviceName == $svc)
  ')"

  echo "$service_json" | jq '{
    serviceName,
    desiredCount,
    runningCount,
    pendingCount,
    deployments: [.deployments[] | {status, rolloutState, desiredCount, runningCount, pendingCount, taskDefinition}],
    events: [.events[0:10][] | {createdAt, message}]
  }'

  local task_definition_arn
  task_definition_arn="$(echo "$service_json" | jq -r '[.deployments[] | select(.status == "PRIMARY")][0].taskDefinition // empty')"
  if [[ -z "$task_definition_arn" ]]; then
    return 0
  fi

  local stopped_json
  stopped_json="$(recent_stopped_tasks_json "$service_name" "$task_definition_arn")"
  if [[ "$(echo "$stopped_json" | jq '.tasks | length')" -eq 0 ]]; then
    return 0
  fi

  echo "Recent stopped tasks:"
  echo "$stopped_json" | jq '.tasks'

  local latest_task_arn
  latest_task_arn="$(echo "$stopped_json" | jq -r '.tasks[0].taskArn // empty')"
  if [[ -n "$latest_task_arn" ]]; then
    print_recent_log_excerpt "$task_definition_arn" "$latest_task_arn"
  fi
}

service_has_repeated_startup_failures() {
  local describe_json="$1"
  local service_name="$2"

  local service_json
  service_json="$(echo "$describe_json" | jq --arg svc "$service_name" '
    .services[]
    | select(.serviceName == $svc)
  ')"

  local desired_count running_count pending_count task_definition_arn
  desired_count="$(echo "$service_json" | jq -r '.desiredCount')"
  running_count="$(echo "$service_json" | jq -r '.runningCount')"
  pending_count="$(echo "$service_json" | jq -r '.pendingCount')"
  task_definition_arn="$(echo "$service_json" | jq -r '[.deployments[] | select(.status == "PRIMARY")][0].taskDefinition // empty')"

  if [[ "$desired_count" -eq 0 || "$running_count" -gt 0 || "$pending_count" -gt 0 || -z "$task_definition_arn" ]]; then
    return 1
  fi

  local stopped_json
  stopped_json="$(recent_stopped_tasks_json "$service_name" "$task_definition_arn")"

  local fatal_count
  fatal_count="$(echo "$stopped_json" | jq '
    [
      .tasks[]
      | select(
          (.stopCode // "") == "EssentialContainerExited"
          or (.stopCode // "") == "TaskFailedToStart"
          or ([.containers[] | select((.exitCode // 0) != 0 or ((.reason // "") != ""))] | length) > 0
        )
    ] | length
  ')"

  [[ "$fatal_count" -ge 2 ]]
}

deadline="$(( $(date +%s) + TIMEOUT_SECONDS ))"

while true; do
  describe_json="$(aws_json ecs describe-services \
    --cluster "$CLUSTER" \
    --services "${SERVICES[@]}" \
    --output json)"

  echo "Current ECS rollout status:"
  service_status_lines "$describe_json"

  all_stable=true
  for service_name in "${SERVICES[@]}"; do
    if ! service_is_stable "$describe_json" "$service_name"; then
      all_stable=false
    fi
  done

  if [[ "$all_stable" == "true" ]]; then
    exit 0
  fi

  for service_name in "${SERVICES[@]}"; do
    if service_has_repeated_startup_failures "$describe_json" "$service_name"; then
      echo "Detected repeated task startup failures for ECS service '$service_name'." >&2
      print_service_diagnostics "$describe_json" "$service_name"
      exit 1
    fi
  done

  if (( "$(date +%s)" >= deadline )); then
    echo "Timed out waiting for ECS services to stabilize after ${TIMEOUT_SECONDS}s." >&2
    echo "Recent service diagnostics:"
    for service_name in "${SERVICES[@]}"; do
      print_service_diagnostics "$describe_json" "$service_name"
    done
    exit 1
  fi

  sleep "$SLEEP_SECONDS"
done

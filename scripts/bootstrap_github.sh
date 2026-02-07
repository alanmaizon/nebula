#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=false
SYNC_WIKI=false
WIKI_ONLY=false
REPO=""

usage() {
  cat <<'USAGE'
Bootstrap GitHub governance artifacts for this repository.

Usage:
  scripts/bootstrap_github.sh [--repo owner/repo] [--dry-run] [--sync-wiki] [--wiki-only]

Options:
  --repo owner/repo  Override repository target (default: inferred from git origin)
  --dry-run          Print actions without executing them
  --sync-wiki        Push docs/wiki/*.md pages to the GitHub wiki repository
  --wiki-only        Run only wiki sync flow (skip labels/milestones/issues/project)
  --help             Show this message
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --sync-wiki)
      SYNC_WIKI=true
      shift
      ;;
    --wiki-only)
      WIKI_ONLY=true
      SYNC_WIKI=true
      shift
      ;;
    --help|-h)
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

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

run() {
  if $DRY_RUN; then
    printf 'DRY-RUN:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

infer_repo_from_origin() {
  local origin_url
  origin_url="$(git remote get-url origin)"
  case "$origin_url" in
    git@github.com:*.git)
      echo "${origin_url#git@github.com:}" | sed 's/\.git$//'
      ;;
    https://github.com/*)
      echo "${origin_url#https://github.com/}" | sed 's/\.git$//'
      ;;
    *)
      echo "Could not infer GitHub repository from origin URL: $origin_url" >&2
      exit 1
      ;;
  esac
}

ensure_label() {
  local name="$1"
  local color="$2"
  local description="$3"
  run gh label create "$name" --repo "$REPO" --color "$color" --description "$description" --force
}

milestone_exists() {
  local title="$1"
  gh api "repos/$REPO/milestones?state=all&per_page=100" --jq '.[].title' | rg -Fxq "$title"
}

ensure_milestone() {
  local title="$1"
  local description="$2"
  if milestone_exists "$title"; then
    echo "Milestone exists: $title"
    return
  fi
  run gh api --method POST "repos/$REPO/milestones" -f title="$title" -f description="$description"
}

issue_exists() {
  local title="$1"
  gh issue list --repo "$REPO" --state all --limit 200 --json title --jq '.[].title' | rg -Fxq "$title"
}

ensure_issue() {
  local title="$1"
  local labels="$2"
  local milestone="$3"
  local body="$4"

  if issue_exists "$title"; then
    echo "Issue exists: $title"
    return
  fi

  run gh issue create \
    --repo "$REPO" \
    --title "$title" \
    --label "$labels" \
    --milestone "$milestone" \
    --body "$body"
}

project_number_by_title() {
  local title="$1"
  gh project list --owner "$OWNER" --limit 100 --format json --jq \
    "if type == \"array\" then .[] else .projects[] end | select(.title == \"$title\") | .number"
}

ensure_project() {
  local title="$1"
  local project_number

  project_number="$(project_number_by_title "$title" || true)"
  if [[ -n "$project_number" ]]; then
    echo "Project exists (#$project_number): $title"
  else
    run gh project create --owner "$OWNER" --title "$title"
    project_number="$(project_number_by_title "$title")"
  fi

  if [[ -n "$project_number" ]]; then
    run gh project link "$project_number" --owner "$OWNER" --repo "$REPO"
  fi
}

sync_wiki_pages() {
  local tmp_dir wiki_repo wiki_remote
  tmp_dir="$(mktemp -d)"
  wiki_remote="https://github.com/$REPO.wiki.git"
  wiki_repo="$tmp_dir/wiki"

  if ! run git clone "$wiki_remote" "$wiki_repo"; then
    cat <<EOF >&2
Could not clone wiki repository: $wiki_remote

For private repositories, GitHub may require an initial wiki page before the
wiki git repository is created.

Open:
  https://github.com/$REPO/wiki

Create a first page (for example "Home"), then rerun:
  scripts/bootstrap_github.sh --wiki-only
EOF
    return 1
  fi

  if ! $DRY_RUN; then
    cp docs/wiki/*.md "$wiki_repo"/
    (
      cd "$wiki_repo"
      if [[ -n "$(git status --short)" ]]; then
        git add *.md
        git commit -m "Bootstrap wiki pages"
        git push
      else
        echo "Wiki already up to date."
      fi
    )
  fi
}

require_command git
require_command gh
require_command rg

if [[ -z "$REPO" ]]; then
  REPO="$(infer_repo_from_origin)"
fi
OWNER="${REPO%%/*}"

if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub CLI is not authenticated. Run: gh auth login -h github.com" >&2
  exit 1
fi

if $WIKI_ONLY; then
  echo "Wiki-only mode for $REPO"
  sync_wiki_pages
  echo "Wiki sync complete."
  exit 0
fi

echo "Bootstrapping GitHub for $REPO"

ensure_label "task" "0052cc" "Scoped engineering or documentation task"
ensure_label "epic" "5319e7" "Cross-cutting multi-issue initiative"
ensure_label "documentation" "1d76db" "Documentation updates"
ensure_label "security" "b60205" "Security controls, fixes, or policy work"
ensure_label "dependencies" "0366d6" "Dependency updates"
ensure_label "blocked" "d73a4a" "Work blocked by dependency or decision"
ensure_label "mvp" "0e8a16" "In current MVP scope"
ensure_label "step-0" "bfdadc" "Step 0 governance and bootstrap"
ensure_label "step-1" "bfdadc" "Step 1 local development foundation"
ensure_label "step-2" "bfdadc" "Step 2 ingestion and metadata pipeline"
ensure_label "step-3" "bfdadc" "Step 3 chunking and retrieval baseline"
ensure_label "step-4" "bfdadc" "Step 4 requirements extraction"
ensure_label "step-5" "bfdadc" "Step 5 cited draft generation"
ensure_label "step-6" "bfdadc" "Step 6 coverage matrix and validation"
ensure_label "step-7" "bfdadc" "Step 7 export and UX completion"
ensure_label "step-8" "bfdadc" "Step 8 security and reliability hardening"
ensure_label "step-9" "bfdadc" "Step 9 demo freeze and release"

ensure_milestone "Step 0 - Governance" "Repository governance and project controls baseline."
ensure_milestone "Step 1 - Foundation" "Local development environment and skeleton services."
ensure_milestone "Step 2 - Ingestion" "Upload, parsing, and metadata pipeline."
ensure_milestone "Step 3 - Retrieval" "Chunking, embeddings, and evidence retrieval."
ensure_milestone "Step 4 - Requirements" "RFP requirements extraction and schema enforcement."
ensure_milestone "Step 5 - Cited Drafting" "Evidence-grounded section generation."
ensure_milestone "Step 6 - Coverage" "Coverage matrix and missing evidence generation."
ensure_milestone "Step 7 - Export and UX" "Export artifacts and demo UI completion."
ensure_milestone "Step 8 - Hardening" "Security and reliability baseline controls."
ensure_milestone "Step 9 - Release" "Demo freeze, release, and runbook finalization."

ensure_issue \
  "[Step 0] Finalize repository governance baseline" \
  "task,mvp,step-0,documentation,security" \
  "Step 0 - Governance" \
  "Complete templates, security policy, workflows, and GitHub setup automation."

ensure_issue \
  "[Step 1] Scaffold backend and frontend directories" \
  "task,mvp,step-1" \
  "Step 1 - Foundation" \
  "Create initial FastAPI and Next.js skeletons, env templates, and local startup instructions."

ensure_issue \
  "[Step 2] Implement upload and metadata pipeline" \
  "task,mvp,step-2" \
  "Step 2 - Ingestion" \
  "Add project/document models plus upload endpoint with persisted metadata."

ensure_issue \
  "[Step 3] Add chunking and retrieval baseline" \
  "task,mvp,step-3" \
  "Step 3 - Retrieval" \
  "Build chunking, embeddings, indexing, and project-scoped top-k retrieval."

ensure_issue \
  "[Step 4] Implement requirements extraction endpoint" \
  "task,mvp,step-4" \
  "Step 4 - Requirements" \
  "Generate validated requirements.json with one repair retry on schema failure."

ensure_issue \
  "[Step 5] Implement cited section generation endpoint" \
  "task,mvp,step-5" \
  "Step 5 - Cited Drafting" \
  "Generate cited draft output with evidence-grounded citations and missing evidence flags."

ensure_issue \
  "[Step 6] Implement coverage matrix computation" \
  "task,mvp,step-6" \
  "Step 6 - Coverage" \
  "Produce met/partial/missing coverage entries linked to requirement and evidence references."

ensure_issue \
  "[Step 7] Implement JSON and Markdown exports" \
  "task,mvp,step-7" \
  "Step 7 - Export and UX" \
  "Add export endpoint and UI controls for JSON + Markdown artifact download."

ensure_issue \
  "[Step 8] Add logging, redaction, and backup runbook" \
  "task,mvp,step-8,security,documentation" \
  "Step 8 - Hardening" \
  "Introduce correlation IDs, sensitive-data logging rules, and documented backup/restore steps."

ensure_issue \
  "[Step 9] Run demo freeze checklist and tag v0.1.0" \
  "task,mvp,step-9,documentation" \
  "Step 9 - Release" \
  "Run full demo from clean setup, capture release notes, and publish initial MVP tag."

ensure_project "Nebula MVP Roadmap"

if $SYNC_WIKI; then
  sync_wiki_pages
fi

echo "Bootstrap complete."

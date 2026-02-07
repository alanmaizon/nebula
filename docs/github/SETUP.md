# GitHub Setup Runbook

This runbook bootstraps the repository for disciplined delivery: wiki, project board, milestones, labels, issues, and PR process.

## Prerequisites
- GitHub CLI installed (`gh --version`)
- Valid GitHub auth token (`gh auth login -h github.com`)
- Token includes `repo`, `workflow`, and `project` scopes

To add project scope to an existing token:

```bash
gh auth refresh -h github.com -s project
```

## 1) Bootstrap Governance Artifacts

Dry run:

```bash
scripts/bootstrap_github.sh --dry-run
```

Execute:

```bash
scripts/bootstrap_github.sh
```

Override repository target:

```bash
scripts/bootstrap_github.sh --repo owner/repo
```

This script creates/updates:
- labels
- milestones (`Step 0` through `Step 9`)
- starter issues for each step
- project board titled `Nebula MVP Roadmap`
- repository link to the project

## 2) Seed GitHub Wiki

Local wiki source pages are in `docs/wiki/`.

If this is the first wiki publish and the wiki appears empty, initialize it once:
- Open `https://github.com/alanmaizon/grantsmith/wiki`
- Create a first page (for example `Home`)

To sync them to GitHub wiki:

```bash
scripts/bootstrap_github.sh --sync-wiki
```

If your token does not have project scopes yet, run wiki sync only:

```bash
scripts/bootstrap_github.sh --wiki-only
```

## 3) Project Operating Model

- Convert each checklist item into an issue.
- Link each PR to one issue.
- Move cards in project board: `Todo` -> `In Progress` -> `Done`.
- At milestone close, publish retrospective notes to wiki.

## 4) Pull Request Discipline

Required for every PR:
- linked issue
- validation evidence (tests or explicit test gap)
- docs updates for behavioral/config changes
- security checklist confirmation

## 5) Weekly Cadence

- Update issue statuses and board columns.
- Review dependency/security workflow alerts.
- Update `docs/status.yml` and run:

```bash
python scripts/sync_docs.py
```

- Open one summary PR for status/doc updates if needed.

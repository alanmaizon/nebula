# Release Checklist

Use this checklist before tagging a release.

## Single Source of Truth
- Runtime/API version source: `backend/app/version.py` (`APP_VERSION`).
- FastAPI docs version must be wired from `APP_VERSION` in `backend/app/main.py`.
- Current release notes file must be: `docs/wiki/Release-Notes-v<APP_VERSION>.md`.

## Pre-Release Validation
- [ ] All milestone issues are closed or explicitly deferred.
- [ ] CI passes on `main`.
- [ ] `python scripts/check_release_consistency.py` passes.
- [ ] Docs reflect current setup and endpoint behavior.
- [ ] Security alerts are triaged and critical findings resolved.
- [ ] Demo script passes twice from a clean startup.
- [ ] Submission readiness dry-run completed via `docs/wiki/Nova-Submission-Checklist.md`.
- [ ] Known limitations are documented.

## Version Bump Procedure
1. Update `APP_VERSION` in `backend/app/version.py`.
2. Create/update release notes file `docs/wiki/Release-Notes-vX.Y.Z.md` with header `# Release Notes - vX.Y.Z`.
3. Ensure `docs/wiki/Home.md` includes `[Release Notes vX.Y.Z](Release-Notes-vX.Y.Z)`.
4. Open PR and confirm `version-consistency` CI job is green.
5. Tag release with `git tag vX.Y.Z` and push the tag.

## Evidence
- Demo-freeze evidence: `docs/wiki/Demo-Freeze-2026-02-11.md`.
- Submission checklist: `docs/wiki/Nova-Submission-Checklist.md`.

# Devpost Testing Instructions - 2026-02-08

Use this as the source for the Devpost "Testing Instructions for Application" section.

## Paste-Ready Devpost Text
To run Nebula locally for judging, use Docker and valid AWS Bedrock credentials.

1. Prerequisites:
   - Docker Desktop running
   - Git clone of this repository
   - AWS credentials with Bedrock access
2. Choose one AWS credential flow:
   - Option A (AWS SSO):
   - `aws sso login --profile <your_profile>`
   - `eval "$(aws configure export-credentials --profile <your_profile> --format env)"`
   - `aws sts get-caller-identity`
   - Option B (Access keys):
   - `export AWS_ACCESS_KEY_ID=<your_key>`
   - `export AWS_SECRET_ACCESS_KEY=<your_secret>`
   - `export AWS_SESSION_TOKEN=<your_session_token>` (if using temporary credentials)
3. Set Bedrock region/model environment variables:
   - `export AWS_REGION=<bedrock_enabled_region>` (example: `us-east-1`)
   - `export BEDROCK_MODEL_ID=amazon.nova-pro-v1:0`
   - `export BEDROCK_LITE_MODEL_ID=amazon.nova-lite-v1:0`
   - Ensure your selected model IDs are available in the region set in `AWS_REGION`.
4. Start the stack:
   - `scripts/run_docker_env.sh restart`
5. Access the app:
   - Frontend: `http://localhost:3000`
   - Backend docs: `http://localhost:8000/docs`
6. Run the full demo flow check:
   - `scripts/run_demo_freeze.sh judge-run`
7. Verify outputs:
   - `/tmp/nebula-demo-freeze/judge-run/summary.txt`
   - `/tmp/nebula-demo-freeze/judge-run/full_draft.json`
   - `/tmp/nebula-demo-freeze/judge-run/export.json`
   - `/tmp/nebula-demo-freeze/judge-run/export.md`
8. Stop the stack:
   - `scripts/run_docker_env.sh down`

## Maintainer Notes
- If Bedrock credentials are missing/expired, extraction/generation endpoints will return `502` with an explicit Bedrock credential/runtime error.
- Keep this page aligned with:
  - `scripts/run_docker_env.sh`
  - `scripts/run_demo_freeze.sh`
  - `README.md` runtime instructions

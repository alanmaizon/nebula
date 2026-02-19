# AWS Production Deployment Checklist

This checklist covers the production gaps between local MVP behavior and AWS ECS deployment.

## 1) Configure GitHub Secrets for Deploy Workflow

Workflow file: `.github/workflows/deploy-aws.yml`

Required (backend deploy):
- `AWS_REGION`: AWS region where ECS/ECR are deployed.
- `AWS_ROLE_TO_ASSUME`: IAM role ARN assumed by GitHub Actions (OIDC).
- `ECR_BACKEND_REPOSITORY`: backend ECR repo name (not full URI).
- `ECS_CLUSTER`: ECS cluster name.
- `ECS_BACKEND_SERVICE`: ECS backend service name.

Required only when deploying frontend via the same workflow:
- `ECR_FRONTEND_REPOSITORY`: frontend ECR repo name.
- `ECS_FRONTEND_SERVICE`: ECS frontend service name.
- `NEXT_PUBLIC_API_BASE`: API base baked into frontend build.
  - recommended value: `/api` (same-origin routing through CloudFront).
  - fallback value: absolute `https://...` API origin.
  - anti-pattern: absolute `http://...` API origin (blocked on HTTPS pages).

Required only when frontend auth is enabled (`NEXT_PUBLIC_AUTH_ENABLED=true`):
- `NEXT_PUBLIC_COGNITO_DOMAIN`: Cognito hosted UI domain (no scheme required, scheme allowed).
- `NEXT_PUBLIC_COGNITO_CLIENT_ID`: Cognito app client ID used by the frontend.
- `NEXT_PUBLIC_COGNITO_REDIRECT_URI`: frontend callback URI registered in Cognito.

Optional when frontend auth is enabled:
- `NEXT_PUBLIC_COGNITO_LOGOUT_REDIRECT_URI`: post-logout redirect URI.
- `NEXT_PUBLIC_COGNITO_SCOPE`: OAuth scopes (default `openid email profile`).

Optional:
- `ECS_BACKEND_CONTAINER_NAME`: backend container name in task definition.
  - default if omitted: `ECS_BACKEND_SERVICE` value.
- `ECS_FRONTEND_CONTAINER_NAME`: frontend container name in task definition.
  - default if omitted: `ECS_FRONTEND_SERVICE` value.

Example setup commands:

```bash
gh secret set AWS_REGION --repo alanmaizon/nebula --body "eu-central-1"
gh secret set AWS_ROLE_TO_ASSUME --repo alanmaizon/nebula --body "arn:aws:iam::<account-id>:role/<github-deploy-role>"
gh secret set ECR_BACKEND_REPOSITORY --repo alanmaizon/nebula --body "nebula-backend"
gh secret set ECS_CLUSTER --repo alanmaizon/nebula --body "nebula-cluster"
gh secret set ECS_BACKEND_SERVICE --repo alanmaizon/nebula --body "nebula-backend"
```

Frontend secrets (only if frontend is deployed by this workflow):

```bash
gh secret set ECR_FRONTEND_REPOSITORY --repo alanmaizon/nebula --body "nebula-frontend"
gh secret set ECS_FRONTEND_SERVICE --repo alanmaizon/nebula --body "nebula-frontend"
gh secret set NEXT_PUBLIC_API_BASE --repo alanmaizon/nebula --body "/api"
```

Frontend auth secrets (only if Cognito auth is enabled):

```bash
gh secret set NEXT_PUBLIC_AUTH_ENABLED --repo alanmaizon/nebula --body "true"
gh secret set NEXT_PUBLIC_COGNITO_DOMAIN --repo alanmaizon/nebula --body "your-domain.auth.eu-central-1.amazoncognito.com"
gh secret set NEXT_PUBLIC_COGNITO_CLIENT_ID --repo alanmaizon/nebula --body "<cognito-app-client-id>"
gh secret set NEXT_PUBLIC_COGNITO_REDIRECT_URI --repo alanmaizon/nebula --body "https://<frontend-host>/"
gh secret set NEXT_PUBLIC_COGNITO_LOGOUT_REDIRECT_URI --repo alanmaizon/nebula --body "https://<frontend-host>/"
gh secret set NEXT_PUBLIC_COGNITO_SCOPE --repo alanmaizon/nebula --body "openid email profile"
```

Optional fallback (if you must call a separate API origin directly):

```bash
gh secret set NEXT_PUBLIC_API_BASE --repo alanmaizon/nebula --body "https://api.example.com"
```

## 2) ECS Runtime Configuration (Task Definitions)

The backend task definition should provide these runtime keys via container `environment` or `secrets`:
- `APP_ENV`
- `AWS_REGION`
- `BEDROCK_MODEL_ID`
- `BEDROCK_LITE_MODEL_ID`
- `BEDROCK_EMBEDDING_MODEL_ID`
- `DATABASE_URL`
- `STORAGE_BACKEND` (`local` or `s3`)
- `S3_BUCKET` (required when `STORAGE_BACKEND=s3`)
- `S3_PREFIX` (optional; defaults to `nebula`)
- `STORAGE_ROOT`
- `CORS_ORIGINS`
- `AUTH_ENABLED` (`true` or `false`)
- `COGNITO_APP_CLIENT_ID` (required when `AUTH_ENABLED=true`)
- `COGNITO_ISSUER` or both `COGNITO_REGION` + `COGNITO_USER_POOL_ID` (required when `AUTH_ENABLED=true`)

Recommendations:
- Use RDS/Postgres for `DATABASE_URL` in production (avoid sqlite on ECS).
- Store uploaded documents in S3 (`STORAGE_BACKEND=s3`) to avoid filling ephemeral container storage.
- If Bedrock returns "on-demand throughput isn't supported", set `BEDROCK_MODEL_ID`/`BEDROCK_LITE_MODEL_ID` to an inference profile ID/ARN (example EU: `eu.amazon.nova-pro-v1:0` / `eu.amazon.nova-lite-v1:0`).
- Keep `AUTH_ENABLED=false` unless frontend Cognito settings are configured and tested end-to-end.

### RDS Postgres (Minimal Setup)
1. Create an RDS Postgres instance (or Aurora Postgres) in the same VPC as ECS, ideally in private subnets.
2. Security group:
   - Allow inbound `5432` from the ECS backend task security group.
3. Configure `DATABASE_URL` for the backend task definition (prefer ECS `secrets` from Secrets Manager).

### S3 Upload Bucket (Minimal Setup)
1. Create an S3 bucket in your deployment region (block public access on).
2. Add lifecycle policy (optional) to expire old uploads.
3. Task role (`nebulaTaskRole`) permissions:
   - `s3:PutObject`, `s3:GetObject`, `s3:ListBucket` scoped to your bucket/prefix.
4. Set backend task definition env vars:
   - `STORAGE_BACKEND=s3`
   - `S3_BUCKET=<your-bucket>`
   - `S3_PREFIX=nebula` (or your desired prefix)

## 3) IAM and OIDC Requirements for GitHub Actions Deploy

The account must contain:
- IAM OIDC provider: `token.actions.githubusercontent.com`
- Deploy role trusted for `sts:AssumeRoleWithWebIdentity`
- Trust policy restricted to your repo and branch
- Policy permissions covering:
  - ECR push (`GetAuthorizationToken`, `BatchCheckLayerAvailability`, `PutImage`, etc.)
  - ECS service/task updates (`DescribeServices`, `DescribeTaskDefinition`, `RegisterTaskDefinition`, `UpdateService`, `DescribeClusters`)
  - IAM pass role for ECS task execution/task roles (`iam:PassRole`) when needed by task definition registration

Minimal trust policy template:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<account-id>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:alanmaizon/nebula:ref:refs/heads/main"
        }
      }
    }
  ]
}
```

## 4) Use the Readiness Checker Before Deploy

Script: `scripts/aws/check_deploy_readiness.sh`

Example:

```bash
AWS_CONFIG_FILE=/tmp/aws-config-nebula \
AWS_PROFILE=nebula \
bash scripts/aws/check_deploy_readiness.sh \
  --region eu-central-1 \
  --cluster nebula-cluster \
  --backend-service nebula-backend \
  --backend-repo nebula-backend \
  --role-arn arn:aws:iam::<account-id>:role/<github-deploy-role>
```

If frontend is deployed separately, add:

```bash
  --frontend-service nebula-frontend \
  --frontend-repo nebula-frontend \
  --frontend-api-base /api
```

## 5) Deployment Behavior in Updated Workflow

`.github/workflows/deploy-aws.yml` now:
- validates required secrets and fails fast when missing
- supports backend-only or backend+frontend deployments
- validates AWS readiness before image build/push
- pins images by commit SHA in ECS task definition revisions
- updates ECS services to the new task definition revision (no `:latest` force-redeploy dependency)

## 6) CloudFront and ALB Routing Pattern (Recommended)

Use one CloudFront distribution and route API traffic by path:
- CloudFront behavior `Path pattern = /api/*`
  - Origin: ALB
  - Allowed methods: include API methods needed by backend
  - Cache policy: disabled for API behavior
- CloudFront default behavior (`/*`)
  - Origin: frontend service
- ALB listener rules
  - `/api/*` -> backend target group
  - `/*` -> frontend target group
- Viewer protocol policy: HTTPS-only

After deploying a new frontend image, invalidate CloudFront paths:
- `/`
- `/_next/static/*`

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
- `NEXT_PUBLIC_API_BASE`: API base URL baked into frontend build.

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
- `STORAGE_ROOT`
- `CORS_ORIGINS`

Recommendations:
- Use RDS/Postgres for `DATABASE_URL` in production.
- Use persistent storage for `STORAGE_ROOT` (S3 and/or durable mounted storage), not ephemeral container-local paths.

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
  --frontend-repo nebula-frontend
```

## 5) Deployment Behavior in Updated Workflow

`.github/workflows/deploy-aws.yml` now:
- validates required secrets and fails fast when missing
- supports backend-only or backend+frontend deployments
- validates AWS readiness before image build/push
- pins images by commit SHA in ECS task definition revisions
- updates ECS services to the new task definition revision (no `:latest` force-redeploy dependency)

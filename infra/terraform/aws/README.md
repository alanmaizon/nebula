# Nebula AWS Terraform

This stack provisions the baseline AWS footprint the repo already expects:

- CloudFront in front of an ALB
- ECS Fargate services for `nebula-frontend` and `nebula-backend`
- ECR repositories for both images
- RDS Postgres with a generated `DATABASE_URL` stored in Secrets Manager
- S3 for uploads and backup copies
- IAM roles for ECS tasks and the GitHub OIDC deploy workflows

It is designed to coexist with the existing GitHub Actions workflows in this repo. Terraform creates the baseline ECS services and initial task definitions, and then the GitHub deploy/pause/resume workflows can keep owning day-two rollouts and desired-count changes.

## Design Choices

- ECS tasks run in public subnets by default so the stack avoids NAT gateway baseline cost.
- RDS still stays in private database subnets and only accepts traffic from the backend ECS service.
- CloudFront forwards all methods, headers, cookies, and query strings to the ALB with caching disabled. That keeps the setup predictable for the current dynamic Next.js and API traffic.
- Auth is disabled by default. If you already have Cognito, you can wire its identifiers in through variables and GitHub secrets.

## Files

- `versions.tf`: Terraform and provider constraints
- `variables.tf`: stack inputs
- `main.tf`: AWS resources
- `outputs.tf`: values to feed into GitHub Actions
- `terraform.tfvars.example`: starting point for local configuration

## Bootstrap

1. Copy the example vars file:

   ```bash
   cp terraform.tfvars.example terraform.tfvars
   ```

2. Decide how you want to handle the very first ECS service creation:

   - Recommended: push initial `latest` images to the new ECR repos before the first full apply.
   - Safe fallback: set `backend_desired_count = 0` and `frontend_desired_count = 0`, apply infrastructure first, then push images and use the repo’s `Resume AWS` or `Deploy AWS` workflow afterward.

3. Initialize Terraform:

   ```bash
   terraform init
   ```

4. Review the plan:

   ```bash
   terraform plan
   ```

5. Apply:

   ```bash
   terraform apply
   ```

If you are aiming this at an account that already has parts of Nebula deployed, either import the matching resources into this state or change the names/variables first. This stack assumes a clean baseline by default.

## GitHub Actions Wiring

After apply, capture the outputs:

```bash
terraform output -json github_actions_secrets
terraform output -json github_actions_vars
```

Load the `github_actions_secrets` map into repository secrets and the `github_actions_vars` map into repository variables. Those outputs line up with the workflows already in:

- `.github/workflows/deploy-aws.yml`
- `.github/workflows/resume-aws.yml`
- `.github/workflows/pause-aws.yml`
- `.github/workflows/backup-aws.yml`

If you prefer a guided GitHub Actions path for provisioning a fresh stack, run `.github/workflows/provision-aws.yml`. After a successful `apply`, it prints the exact `gh secret set` / `gh variable set` commands you need for the repo.

The most important values are:

- `AWS_ROLE_TO_ASSUME`
- `ECS_CLUSTER`
- `ECS_BACKEND_SERVICE`
- `ECS_FRONTEND_SERVICE`
- `ECR_BACKEND_REPOSITORY`
- `ECR_FRONTEND_REPOSITORY`
- `DB_INSTANCE_ID`
- `BACKUP_S3_BUCKET`

You can also generate the GitHub wiring commands locally:

```bash
terraform output -json > tf-output.json
scripts/aws/render_github_actions_settings_from_tf.sh tf-output.json alanmaizon/nebula
```

## Operational Notes

- The generated Postgres password is stored in Terraform state because Terraform has to build the `DATABASE_URL` secret. Use remote state with encryption before you treat this as a long-lived production stack.
- The ECS services intentionally ignore drift for `desired_count` and `task_definition`. That keeps Terraform from undoing the repo’s deploy and pause/resume workflows.
- If you change backend environment variables or IAM roles in Terraform later, follow up with a fresh ECS deployment so the running service picks up the new task definition.

## Next Hardening Steps

- Move ECS tasks to private subnets and add NAT or VPC endpoints if you want stricter networking.
- Add a custom domain, ACM certificate, and Route 53 records for CloudFront.
- Expand auth from `backend_auth_enabled = false` to a real Cognito user pool and frontend build-time variables.
- Add remote state storage, for example an S3 backend plus DynamoDB locking.

output "cloudfront_domain_name" {
  description = "Primary HTTPS entrypoint for Nebula."
  value       = aws_cloudfront_distribution.app.domain_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID for invalidations."
  value       = aws_cloudfront_distribution.app.id
}

output "alb_dns_name" {
  description = "ALB DNS name for direct debugging."
  value       = aws_lb.app.dns_name
}

output "ecs_cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.main.name
}

output "backend_service_name" {
  description = "Backend ECS service name."
  value       = aws_ecs_service.backend.name
}

output "frontend_service_name" {
  description = "Frontend ECS service name."
  value       = aws_ecs_service.frontend.name
}

output "backend_ecr_repository_name" {
  description = "Backend ECR repository name."
  value       = aws_ecr_repository.backend.name
}

output "frontend_ecr_repository_name" {
  description = "Frontend ECR repository name."
  value       = aws_ecr_repository.frontend.name
}

output "uploads_bucket_name" {
  description = "S3 bucket used for uploads and backup copies."
  value       = aws_s3_bucket.uploads.id
}

output "database_endpoint" {
  description = "RDS endpoint hostname."
  value       = aws_db_instance.postgres.address
}

output "database_identifier" {
  description = "RDS instance identifier."
  value       = aws_db_instance.postgres.identifier
}

output "database_url_secret_name" {
  description = "Secrets Manager name that backs DATABASE_URL in ECS."
  value       = aws_secretsmanager_secret.database_url.name
}

output "database_url_secret_arn" {
  description = "Secrets Manager ARN that backs DATABASE_URL in ECS."
  value       = aws_secretsmanager_secret.database_url.arn
}

output "github_actions_secrets" {
  description = "Values to load into GitHub Actions secrets for the existing deploy workflow."
  value = {
    AWS_REGION                        = var.aws_region
    AWS_ROLE_TO_ASSUME                = aws_iam_role.github_deploy.arn
    ECR_BACKEND_REPOSITORY            = aws_ecr_repository.backend.name
    ECR_FRONTEND_REPOSITORY           = aws_ecr_repository.frontend.name
    ECS_CLUSTER                       = aws_ecs_cluster.main.name
    ECS_BACKEND_SERVICE               = aws_ecs_service.backend.name
    ECS_FRONTEND_SERVICE              = aws_ecs_service.frontend.name
    ECS_BACKEND_CONTAINER_NAME        = aws_ecs_service.backend.name
    ECS_FRONTEND_CONTAINER_NAME       = aws_ecs_service.frontend.name
    NEXT_PUBLIC_API_BASE              = "/api"
    NEXT_PUBLIC_AUTH_ENABLED          = var.backend_auth_enabled ? "true" : "false"
    NEXT_PUBLIC_COGNITO_DOMAIN        = ""
    NEXT_PUBLIC_COGNITO_CLIENT_ID     = var.cognito_app_client_id
    NEXT_PUBLIC_COGNITO_REDIRECT_URI  = ""
    NEXT_PUBLIC_COGNITO_LOGOUT_REDIRECT_URI = ""
    NEXT_PUBLIC_COGNITO_SCOPE         = "openid email profile"
  }
}

output "github_actions_vars" {
  description = "Values to load into GitHub Actions repository variables for ops workflows."
  value = {
    DB_INSTANCE_ID             = aws_db_instance.postgres.identifier
    BACKUP_S3_BUCKET           = aws_s3_bucket.uploads.id
    BACKUP_S3_PREFIX           = local.backup_s3_prefix
    RDS_BACKUP_RETENTION_DAYS  = tostring(var.rds_backup_retention_period)
  }
}

output "github_deploy_role_arn" {
  description = "IAM role ARN assumed by GitHub Actions through OIDC."
  value       = aws_iam_role.github_deploy.arn
}

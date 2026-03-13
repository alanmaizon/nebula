variable "aws_region" {
  description = "AWS region for the Nebula stack."
  type        = string
  default     = "eu-central-1"
}

variable "project_name" {
  description = "Base name used for AWS resources."
  type        = string
  default     = "nebula"
}

variable "environment" {
  description = "Environment label applied to tags and bucket naming."
  type        = string
  default     = "prod"
}

variable "tags" {
  description = "Extra tags to attach to supported resources."
  type        = map(string)
  default     = {}
}

variable "vpc_cidr" {
  description = "CIDR block for the application VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "availability_zone_count" {
  description = "How many AZs to spread public and database subnets across."
  type        = number
  default     = 2

  validation {
    condition     = var.availability_zone_count >= 2
    error_message = "availability_zone_count must be at least 2."
  }
}

variable "alb_ingress_cidrs" {
  description = "CIDR blocks allowed to reach the ALB."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "backend_cpu" {
  description = "CPU units for the backend task."
  type        = number
  default     = 1024
}

variable "backend_memory" {
  description = "Memory in MiB for the backend task."
  type        = number
  default     = 2048
}

variable "frontend_cpu" {
  description = "CPU units for the frontend task."
  type        = number
  default     = 512
}

variable "frontend_memory" {
  description = "Memory in MiB for the frontend task."
  type        = number
  default     = 1024
}

variable "backend_desired_count" {
  description = "Initial desired count for the backend service."
  type        = number
  default     = 1
}

variable "frontend_desired_count" {
  description = "Initial desired count for the frontend service."
  type        = number
  default     = 1
}

variable "backend_image_tag" {
  description = "Image tag Terraform should use for the initial backend task definition."
  type        = string
  default     = "latest"
}

variable "frontend_image_tag" {
  description = "Image tag Terraform should use for the initial frontend task definition."
  type        = string
  default     = "latest"
}

variable "backend_container_port" {
  description = "Container port exposed by the backend app."
  type        = number
  default     = 8000
}

variable "frontend_container_port" {
  description = "Container port exposed by the frontend app."
  type        = number
  default     = 3000
}

variable "backend_health_check_path" {
  description = "ALB health check path for the backend target group."
  type        = string
  default     = "/ready"
}

variable "frontend_health_check_path" {
  description = "ALB health check path for the frontend target group."
  type        = string
  default     = "/api/health"
}

variable "assign_public_ip" {
  description = "Assign public IPs to ECS tasks. Enabled here to avoid NAT gateway baseline cost."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch log retention for ECS task logs."
  type        = number
  default     = 30
}

variable "cloudfront_price_class" {
  description = "CloudFront price class."
  type        = string
  default     = "PriceClass_100"
}

variable "cloudfront_wait_for_deployment" {
  description = "Whether terraform apply should block until the CloudFront distribution is fully deployed."
  type        = bool
  default     = false
}

variable "ecr_max_image_count" {
  description = "How many tagged images to keep in each ECR repository."
  type        = number
  default     = 25
}

variable "uploads_bucket_force_destroy" {
  description = "Allow terraform destroy to delete a non-empty uploads bucket."
  type        = bool
  default     = false
}

variable "s3_prefix" {
  description = "Logical prefix used by the backend when storing uploads."
  type        = string
  default     = "nebula"
}

variable "db_name" {
  description = "Database name created inside RDS."
  type        = string
  default     = "nebula"
}

variable "db_username" {
  description = "Primary application user for RDS."
  type        = string
  default     = "nebula"
}

variable "db_port" {
  description = "Database port."
  type        = number
  default     = 5432
}

variable "database_secret_name" {
  description = "Secrets Manager name for the application DATABASE_URL secret. Leave empty to derive from project_name."
  type        = string
  default     = ""
}

variable "rds_instance_class" {
  description = "RDS instance class for Postgres."
  type        = string
  default     = "db.t4g.micro"
}

variable "rds_engine_version" {
  description = "Optional Postgres engine version. Leave null to let AWS choose the regional default."
  type        = string
  default     = null
  nullable    = true
}

variable "rds_allocated_storage" {
  description = "Allocated storage in GiB for the primary Postgres instance."
  type        = number
  default     = 20
}

variable "rds_max_allocated_storage" {
  description = "Maximum autoscaled storage in GiB for the primary Postgres instance."
  type        = number
  default     = 100
}

variable "rds_backup_retention_period" {
  description = "Automated backup retention window in days."
  type        = number
  default     = 7
}

variable "rds_multi_az" {
  description = "Enable Multi-AZ for Postgres."
  type        = bool
  default     = false
}

variable "rds_deletion_protection" {
  description = "Protect the RDS instance from deletion."
  type        = bool
  default     = true
}

variable "rds_skip_final_snapshot" {
  description = "Skip the final DB snapshot during terraform destroy."
  type        = bool
  default     = false
}

variable "rds_apply_immediately" {
  description = "Apply RDS modifications immediately."
  type        = bool
  default     = true
}

variable "bedrock_model_id" {
  description = "Primary Bedrock model or inference profile ID used for longer-form generation."
  type        = string
  default     = "eu.amazon.nova-pro-v1:0"
}

variable "bedrock_lite_model_id" {
  description = "Bedrock model or inference profile ID used for lightweight planning and coverage calls."
  type        = string
  default     = "eu.amazon.nova-lite-v1:0"
}

variable "bedrock_embedding_model_id" {
  description = "Bedrock embedding model ID."
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "embedding_mode" {
  description = "Embedding mode for the backend."
  type        = string
  default     = "bedrock"
}

variable "bedrock_validate_model_ids_on_startup" {
  description = "Whether the backend should validate Bedrock model IDs during startup."
  type        = bool
  default     = false
}

variable "backend_log_level" {
  description = "Backend application log level."
  type        = string
  default     = "INFO"
}

variable "backend_cors_origins" {
  description = "Explicit backend CORS origins. Leave empty to allow the generated CloudFront domain."
  type        = list(string)
  default     = []
}

variable "backend_auth_enabled" {
  description = "Enable Cognito-backed auth checks in the backend."
  type        = bool
  default     = false
}

variable "cognito_app_client_id" {
  description = "Cognito app client ID used by the backend when auth is enabled."
  type        = string
  default     = ""
}

variable "cognito_issuer" {
  description = "Full Cognito issuer URL used by the backend when auth is enabled."
  type        = string
  default     = ""
}

variable "cognito_region" {
  description = "Cognito region used by the backend when auth is enabled."
  type        = string
  default     = ""
}

variable "cognito_user_pool_id" {
  description = "Cognito user pool ID used by the backend when auth is enabled."
  type        = string
  default     = ""
}

variable "backend_additional_environment" {
  description = "Extra plain-text backend environment variables."
  type        = map(string)
  default     = {}
}

variable "backend_additional_secret_arns" {
  description = "Extra backend secret environment variables, keyed by env var name and valued with secret ARN."
  type        = map(string)
  default     = {}
}

variable "github_repository" {
  description = "GitHub repository allowed to assume the deploy role."
  type        = string
  default     = "alanmaizon/nebula"
}

variable "github_ref" {
  description = "Git ref allowed to assume the deploy role."
  type        = string
  default     = "refs/heads/main"
}

variable "github_oidc_provider_arn" {
  description = "Existing GitHub OIDC provider ARN. Leave null to create token.actions.githubusercontent.com in this stack."
  type        = string
  default     = null
  nullable    = true
}

variable "github_oidc_thumbprints" {
  description = "Thumbprints for a Terraform-managed GitHub OIDC provider."
  type        = list(string)
  default     = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

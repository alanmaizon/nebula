data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

resource "random_password" "database" {
  length           = 32
  special          = true
  override_special = "_-!@#%^*"
}

resource "random_id" "final_snapshot" {
  byte_length = 4
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, var.availability_zone_count)

  name_prefix            = var.project_name
  cluster_name           = "${local.name_prefix}-cluster"
  backend_service_name   = "${local.name_prefix}-backend"
  frontend_service_name  = "${local.name_prefix}-frontend"
  database_identifier    = "${local.name_prefix}-postgres"
  database_secret_name   = trimspace(var.database_secret_name) != "" ? var.database_secret_name : "${local.name_prefix}/database_url"
  uploads_bucket_name    = lower("${local.name_prefix}-${var.environment}-${data.aws_caller_identity.current.account_id}-${var.aws_region}-uploads")
  github_oidc_provider   = var.github_oidc_provider_arn != null ? var.github_oidc_provider_arn : aws_iam_openid_connect_provider.github[0].arn
  s3_prefix_trimmed      = trim(var.s3_prefix, "/")
  backup_s3_prefix       = local.s3_prefix_trimmed != "" ? "${local.s3_prefix_trimmed}/backups" : "backups"
  uploads_object_arn     = local.s3_prefix_trimmed != "" ? "${aws_s3_bucket.uploads.arn}/${local.s3_prefix_trimmed}/*" : "${aws_s3_bucket.uploads.arn}/*"
  database_url           = format("postgresql://%s:%s@%s:%d/%s?sslmode=require", var.db_username, urlencode(random_password.database.result), aws_db_instance.postgres.address, var.db_port, var.db_name)
  backend_image_uri      = "${aws_ecr_repository.backend.repository_url}:${var.backend_image_tag}"
  frontend_image_uri     = "${aws_ecr_repository.frontend.repository_url}:${var.frontend_image_tag}"
  backend_secret_arns    = concat([aws_secretsmanager_secret.database_url.arn], [for key in sort(keys(var.backend_additional_secret_arns)) : var.backend_additional_secret_arns[key]])
  backend_cors_origins   = length(var.backend_cors_origins) > 0 ? var.backend_cors_origins : ["https://${aws_cloudfront_distribution.app.domain_name}"]
  common_tags = merge(
    {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      Stack       = "nebula-aws"
    },
    var.tags,
  )

  backend_environment_map = merge(
    {
      APP_ENV                              = "production"
      AWS_REGION                           = var.aws_region
      LOG_LEVEL                            = var.backend_log_level
      BEDROCK_MODEL_ID                     = var.bedrock_model_id
      BEDROCK_LITE_MODEL_ID                = var.bedrock_lite_model_id
      BEDROCK_EMBEDDING_MODEL_ID           = var.bedrock_embedding_model_id
      BEDROCK_VALIDATE_MODEL_IDS_ON_STARTUP = var.bedrock_validate_model_ids_on_startup ? "true" : "false"
      EMBEDDING_MODE                       = var.embedding_mode
      STORAGE_BACKEND                      = "s3"
      S3_BUCKET                            = aws_s3_bucket.uploads.id
      S3_PREFIX                            = var.s3_prefix
      STORAGE_ROOT                         = "data/uploads"
      CORS_ORIGINS                         = join(",", local.backend_cors_origins)
      AUTH_ENABLED                         = var.backend_auth_enabled ? "true" : "false"
      COGNITO_APP_CLIENT_ID                = var.backend_auth_enabled ? var.cognito_app_client_id : ""
      COGNITO_ISSUER                       = var.backend_auth_enabled ? var.cognito_issuer : ""
      COGNITO_REGION                       = var.backend_auth_enabled ? var.cognito_region : ""
      COGNITO_USER_POOL_ID                 = var.backend_auth_enabled ? var.cognito_user_pool_id : ""
    },
    var.backend_additional_environment,
  )

  backend_environment = [
    for key in sort(keys(local.backend_environment_map)) : {
      name  = key
      value = tostring(local.backend_environment_map[key])
    }
  ]

  backend_secrets = concat(
    [
      {
        name      = "DATABASE_URL"
        valueFrom = aws_secretsmanager_secret.database_url.arn
      }
    ],
    [
      for key in sort(keys(var.backend_additional_secret_arns)) : {
        name      = key
        valueFrom = var.backend_additional_secret_arns[key]
      }
    ],
  )
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-vpc"
  })
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-igw"
  })
}

resource "aws_subnet" "public" {
  for_each = {
    for index, az in local.azs : az => {
      cidr = cidrsubnet(var.vpc_cidr, 8, index)
      az   = az
    }
  }

  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.value.az
  cidr_block              = each.value.cidr
  map_public_ip_on_launch = true

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-public-${each.key}"
    Tier = "public"
  })
}

resource "aws_subnet" "database" {
  for_each = {
    for index, az in local.azs : az => {
      cidr = cidrsubnet(var.vpc_cidr, 8, index + 10)
      az   = az
    }
  }

  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.value.az
  cidr_block              = each.value.cidr
  map_public_ip_on_launch = false

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-db-${each.key}"
    Tier = "database"
  })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-public-rt"
  })
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_db_subnet_group" "database" {
  name       = "${local.name_prefix}-db-subnets"
  subnet_ids = [for subnet in aws_subnet.database : subnet.id]

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-db-subnets"
  })
}

resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb-sg"
  description = "Public ingress for the Nebula ALB"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.alb_ingress_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-alb-sg"
  })
}

resource "aws_security_group" "frontend" {
  name        = "${local.name_prefix}-frontend-sg"
  description = "Frontend ECS tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "ALB to frontend"
    from_port       = var.frontend_container_port
    to_port         = var.frontend_container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-frontend-sg"
  })
}

resource "aws_security_group" "backend" {
  name        = "${local.name_prefix}-backend-sg"
  description = "Backend ECS tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "ALB to backend"
    from_port       = var.backend_container_port
    to_port         = var.backend_container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-backend-sg"
  })
}

resource "aws_security_group" "database" {
  name        = "${local.name_prefix}-db-sg"
  description = "Postgres ingress from the backend service"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Backend to Postgres"
    from_port       = var.db_port
    to_port         = var.db_port
    protocol        = "tcp"
    security_groups = [aws_security_group.backend.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-db-sg"
  })
}

resource "aws_ecr_repository" "backend" {
  name                 = local.backend_service_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = merge(local.common_tags, {
    Name = local.backend_service_name
  })
}

resource "aws_ecr_repository" "frontend" {
  name                 = local.frontend_service_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = merge(local.common_tags, {
    Name = local.frontend_service_name
  })
}

resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the most recent tagged backend images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.ecr_max_image_count
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

resource "aws_ecr_lifecycle_policy" "frontend" {
  repository = aws_ecr_repository.frontend.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the most recent tagged frontend images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.ecr_max_image_count
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${local.backend_service_name}"
  retention_in_days = var.log_retention_days
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/ecs/${local.frontend_service_name}"
  retention_in_days = var.log_retention_days
  tags              = local.common_tags
}

resource "aws_s3_bucket" "uploads" {
  bucket        = local.uploads_bucket_name
  force_destroy = var.uploads_bucket_force_destroy
  tags          = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_db_instance" "postgres" {
  identifier                  = local.database_identifier
  engine                      = "postgres"
  engine_version              = var.rds_engine_version
  instance_class              = var.rds_instance_class
  allocated_storage           = var.rds_allocated_storage
  max_allocated_storage       = var.rds_max_allocated_storage
  storage_type                = "gp3"
  db_name                     = var.db_name
  username                    = var.db_username
  password                    = random_password.database.result
  port                        = var.db_port
  db_subnet_group_name        = aws_db_subnet_group.database.name
  vpc_security_group_ids      = [aws_security_group.database.id]
  publicly_accessible         = false
  storage_encrypted           = true
  multi_az                    = var.rds_multi_az
  backup_retention_period     = var.rds_backup_retention_period
  copy_tags_to_snapshot       = true
  skip_final_snapshot         = var.rds_skip_final_snapshot
  final_snapshot_identifier   = var.rds_skip_final_snapshot ? null : "${local.database_identifier}-final-${random_id.final_snapshot.hex}"
  apply_immediately           = var.rds_apply_immediately
  auto_minor_version_upgrade  = true
  deletion_protection         = var.rds_deletion_protection

  tags = merge(local.common_tags, {
    Name = local.database_identifier
  })
}

resource "aws_secretsmanager_secret" "database_url" {
  name = local.database_secret_name

  tags = merge(local.common_tags, {
    Name = local.database_secret_name
  })
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = local.database_url
}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.github_oidc_provider_arn == null ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = var.github_oidc_thumbprints

  tags = local.common_tags
}

data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "${local.name_prefix}TaskExecutionRole"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "task_execution_inline" {
  statement {
    sid     = "ReadInjectedSecrets"
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = local.backend_secret_arns
  }
}

resource "aws_iam_role_policy" "task_execution_inline" {
  name   = "${local.name_prefix}TaskExecutionInline"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_execution_inline.json
}

resource "aws_iam_role" "backend_task" {
  name               = "${local.name_prefix}BackendTaskRole"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "backend_task" {
  statement {
    sid     = "ListUploadsBucket"
    effect  = "Allow"
    actions = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.uploads.arn]
  }

  statement {
    sid     = "ReadWriteUploads"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject"]
    resources = [local.uploads_object_arn]
  }

  statement {
    sid     = "InvokeBedrock"
    effect  = "Allow"
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "backend_task" {
  name   = "${local.name_prefix}BackendTaskPolicy"
  role   = aws_iam_role.backend_task.id
  policy = data.aws_iam_policy_document.backend_task.json
}

resource "aws_iam_role" "frontend_task" {
  name               = "${local.name_prefix}FrontendTaskRole"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "github_assume_role" {
  statement {
    effect = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:${var.github_ref}"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${local.name_prefix}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume_role.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid     = "EcrAuth"
    effect  = "Allow"
    actions = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPushPull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeRepositories",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart"
    ]
    resources = [
      aws_ecr_repository.backend.arn,
      aws_ecr_repository.frontend.arn
    ]
  }

  statement {
    sid    = "EcsDeployAndInspect"
    effect = "Allow"
    actions = [
      "ecs:DescribeClusters",
      "ecs:DescribeServices",
      "ecs:DescribeTaskDefinition",
      "ecs:DescribeTasks",
      "ecs:ListClusters",
      "ecs:ListServices",
      "ecs:ListTaskDefinitions",
      "ecs:RegisterTaskDefinition",
      "ecs:UpdateService"
    ]
    resources = ["*"]
  }

  statement {
    sid    = "PassTaskRoles"
    effect = "Allow"
    actions = ["iam:PassRole"]
    resources = [
      aws_iam_role.task_execution.arn,
      aws_iam_role.backend_task.arn,
      aws_iam_role.frontend_task.arn
    ]
  }

  statement {
    sid    = "RdsPauseResumeBackup"
    effect = "Allow"
    actions = [
      "rds:CreateDBSnapshot",
      "rds:DescribeDBClusters",
      "rds:DescribeDBInstances",
      "rds:DescribeDBSnapshots",
      "rds:ModifyDBInstance",
      "rds:StartDBCluster",
      "rds:StartDBInstance",
      "rds:StopDBCluster",
      "rds:StopDBInstance"
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ReadRuntimeSecrets"
    effect = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = local.backend_secret_arns
  }

  statement {
    sid    = "UploadsBackup"
    effect = "Allow"
    actions = [
      "s3:GetBucketVersioning",
      "s3:ListBucket",
      "s3:PutBucketVersioning"
    ]
    resources = [aws_s3_bucket.uploads.arn]
  }

  statement {
    sid    = "UploadsObjectBackup"
    effect = "Allow"
    actions = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.uploads.arn}/*"]
  }

  statement {
    sid    = "CloudFrontInvalidations"
    effect = "Allow"
    actions = ["cloudfront:CreateInvalidation", "cloudfront:GetDistribution", "cloudfront:GetDistributionConfig"]
    resources = [aws_cloudfront_distribution.app.arn]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "${local.name_prefix}GithubDeployPolicy"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}

resource "aws_ecs_cluster" "main" {
  name = local.cluster_name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = local.common_tags
}

resource "aws_lb" "app" {
  name               = "${local.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = [for subnet in aws_subnet.public : subnet.id]

  tags = local.common_tags
}

resource "aws_lb_target_group" "frontend" {
  name                 = "${local.name_prefix}-front-tg"
  port                 = var.frontend_container_port
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 15

  health_check {
    enabled             = true
    path                = var.frontend_health_check_path
    matcher             = "200-399"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
  }

  tags = local.common_tags
}

resource "aws_lb_target_group" "backend" {
  name                 = "${local.name_prefix}-back-tg"
  port                 = var.backend_container_port
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 15

  health_check {
    enabled             = true
    path                = var.backend_health_check_path
    matcher             = "200"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
  }

  tags = local.common_tags
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

resource "aws_lb_listener_rule" "backend_routes" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }

  condition {
    path_pattern {
      values = ["/api/*", "/health", "/ready"]
    }
  }
}

resource "aws_cloudfront_distribution" "app" {
  enabled             = true
  comment             = "Nebula CloudFront distribution"
  price_class         = var.cloudfront_price_class
  wait_for_deployment = var.cloudfront_wait_for_deployment

  origin {
    domain_name = aws_lb.app.dns_name
    origin_id   = "nebula-alb-origin"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = "nebula-alb-origin"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    min_ttl                = 0
    default_ttl            = 0
    max_ttl                = 0

    forwarded_values {
      query_string = true
      headers      = ["*"]

      cookies {
        forward = "all"
      }
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = local.common_tags
}

resource "aws_ecs_task_definition" "backend" {
  family                   = local.backend_service_name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = tostring(var.backend_cpu)
  memory                   = tostring(var.backend_memory)
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.backend_task.arn

  container_definitions = jsonencode([
    {
      name      = local.backend_service_name
      image     = local.backend_image_uri
      essential = true
      portMappings = [
        {
          containerPort = var.backend_container_port
          hostPort      = var.backend_container_port
          protocol      = "tcp"
        }
      ]
      environment = local.backend_environment
      secrets     = local.backend_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.backend.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])

  tags = local.common_tags
}

resource "aws_ecs_task_definition" "frontend" {
  family                   = local.frontend_service_name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = tostring(var.frontend_cpu)
  memory                   = tostring(var.frontend_memory)
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.frontend_task.arn

  container_definitions = jsonencode([
    {
      name      = local.frontend_service_name
      image     = local.frontend_image_uri
      essential = true
      portMappings = [
        {
          containerPort = var.frontend_container_port
          hostPort      = var.frontend_container_port
          protocol      = "tcp"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.frontend.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])

  tags = local.common_tags
}

resource "aws_ecs_service" "backend" {
  name                               = local.backend_service_name
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.backend.arn
  desired_count                      = var.backend_desired_count
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 120

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    assign_public_ip = var.assign_public_ip
    security_groups  = [aws_security_group.backend.id]
    subnets          = [for subnet in aws_subnet.public : subnet.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = local.backend_service_name
    container_port   = var.backend_container_port
  }

  # GitHub Actions owns steady-state rollouts and pause/resume scaling after bootstrap.
  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }

  depends_on = [aws_lb_listener_rule.backend_routes]
  tags       = local.common_tags
}

resource "aws_ecs_service" "frontend" {
  name                               = local.frontend_service_name
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.frontend.arn
  desired_count                      = var.frontend_desired_count
  launch_type                        = "FARGATE"
  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    assign_public_ip = var.assign_public_ip
    security_groups  = [aws_security_group.frontend.id]
    subnets          = [for subnet in aws_subnet.public : subnet.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = local.frontend_service_name
    container_port   = var.frontend_container_port
  }

  # GitHub Actions owns steady-state rollouts and pause/resume scaling after bootstrap.
  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }

  depends_on = [aws_lb_listener.http]
  tags       = local.common_tags
}

variable "project_name" {
  description = "Short project name used in resource naming."
  type        = string
  default     = "quantgambit"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "production"
}

variable "owner_email" {
  description = "Contact email tagged onto resources."
  type        = string
  default     = "ops@quantgambit.com"
}

variable "aws_region" {
  description = "AWS region for deployment."
  type        = string
  default     = "ap-southeast-1"
}

variable "availability_zone" {
  description = "Specific AZ for the EC2 host. Leave null to use the first available AZ."
  type        = string
  default     = null
}

variable "root_domain" {
  description = "Primary DNS zone for the deployment."
  type        = string
  default     = "quantgambit.com"
}

variable "create_route53_zone" {
  description = "Create a new public Route 53 hosted zone for root_domain."
  type        = bool
  default     = false
}

variable "manage_route53_records" {
  description = "Create Route 53 records for the application hostnames. Set false when DNS is managed outside this stack or the zone ID is not yet available."
  type        = bool
  default     = false
}

variable "existing_route53_zone_id" {
  description = "Existing public Route 53 zone ID. Required when create_route53_zone=false."
  type        = string
  default     = null
}

variable "instance_type" {
  description = "Single application host instance type."
  type        = string
  default     = "m7i-flex.2xlarge"
}

variable "key_name" {
  description = "Optional EC2 key pair for SSH access. Leave null to rely on SSM Session Manager only."
  type        = string
  default     = null
}

variable "ssh_ingress_cidrs" {
  description = "CIDRs allowed to SSH to the instance. Leave empty to disable SSH ingress."
  type        = list(string)
  default     = []
}

variable "vpc_cidr" {
  description = "CIDR for the dedicated VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CIDR for the public subnet that hosts the EC2 instance."
  type        = string
  default     = "10.42.1.0/24"
}

variable "root_volume_size_gb" {
  description = "Root gp3 volume size in GB. This volume stores the app, docker layers, and local databases."
  type        = number
  default     = 250
}

variable "root_volume_iops" {
  description = "gp3 IOPS for the root volume."
  type        = number
  default     = 6000

  validation {
    condition     = var.root_volume_iops >= 3000 && var.root_volume_iops <= 16000
    error_message = "gp3 IOPS must be between 3000 and 16000 for this stack."
  }
}

variable "root_volume_throughput" {
  description = "gp3 throughput in MiB/s for the root volume."
  type        = number
  default     = 250

  validation {
    condition     = var.root_volume_throughput >= 125 && var.root_volume_throughput <= 1000
    error_message = "gp3 throughput must be between 125 and 1000 MiB/s."
  }
}

variable "enable_detailed_monitoring" {
  description = "Enable detailed EC2 monitoring."
  type        = bool
  default     = true
}

variable "alerts_email" {
  description = "Optional email address subscribed to SNS-backed CloudWatch alarms."
  type        = string
  default     = null
}

variable "ssm_parameter_arns" {
  description = "Explicit SSM parameter ARNs the EC2 host may read. Leave empty to use project/environment-scoped defaults."
  type        = list(string)
  default     = []
}

variable "secretsmanager_secret_arns" {
  description = "Explicit Secrets Manager secret ARNs the EC2 host may read. Leave empty to use project/environment-scoped defaults."
  type        = list(string)
  default     = []
}

variable "kms_key_arns" {
  description = "Optional KMS key ARNs the EC2 host may decrypt for SSM parameters or Secrets Manager secrets."
  type        = list(string)
  default     = []
}

variable "deploy_artifact_bucket_name" {
  description = "Optional S3 bucket that stores deploy bundles the EC2 host may download."
  type        = string
  default     = "quantgambit-terraform-state"
}

variable "deploy_artifact_prefix" {
  description = "S3 key prefix under deploy_artifact_bucket_name that stores deploy bundles."
  type        = string
  default     = "deploy-bundles/"
}

variable "manage_app_env_secret" {
  description = "Create and manage the single-EC2 application .env secret in Secrets Manager."
  type        = bool
  default     = true
}

variable "app_env_secret_name" {
  description = "Optional override for the Secrets Manager secret name that stores the deploy .env payload."
  type        = string
  default     = null
}

variable "manage_cloudflare_origin_secret" {
  description = "Create and manage a Secrets Manager secret that stores the Cloudflare origin certificate and private key."
  type        = bool
  default     = false
}

variable "cloudflare_origin_secret_name" {
  description = "Optional override for the Secrets Manager secret name that stores the Cloudflare origin certificate bundle."
  type        = string
  default     = null
}

variable "cloudflare_origin_certificate_pem" {
  description = "Cloudflare origin certificate PEM content."
  type        = string
  sensitive   = true
  default     = null
}

variable "cloudflare_origin_private_key_pem" {
  description = "Cloudflare origin private key PEM content."
  type        = string
  sensitive   = true
  default     = null
}

variable "platform_db_user" {
  description = "Platform Postgres username."
  type        = string
  default     = "platform"
}

variable "platform_db_name" {
  description = "Platform Postgres database name."
  type        = string
  default     = "platform_db"
}

variable "bot_db_user" {
  description = "Bot Timescale/Postgres username."
  type        = string
  default     = "quantgambit"
}

variable "bot_db_name" {
  description = "Bot Timescale/Postgres database name."
  type        = string
  default     = "quantgambit_bot"
}

variable "auth_mode" {
  description = "Authentication mode for the Python API."
  type        = string
  default     = "jwt"
}

variable "allow_unauthenticated" {
  description = "Allow unauthenticated access in the Python API."
  type        = bool
  default     = false
}

variable "active_exchange" {
  description = "Default exchange for the stack."
  type        = string
  default     = "bybit"
}

variable "bybit_demo" {
  description = "Use Bybit demo mode."
  type        = bool
  default     = false
}

variable "bybit_testnet" {
  description = "Use Bybit testnet mode."
  type        = bool
  default     = false
}

variable "order_updates_demo" {
  description = "Use demo order update endpoints."
  type        = bool
  default     = false
}

variable "trading_symbols" {
  description = "Symbols enabled for market data and trading defaults."
  type        = list(string)
  default     = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
}

variable "core_api_port" {
  description = "Internal Node backend port."
  type        = number
  default     = 3001
}

variable "bot_api_port" {
  description = "Internal Python bot API port."
  type        = number
  default     = 3002
}

variable "platform_db_password" {
  description = "Optional explicit platform DB password. Leave null to have Terraform generate one."
  type        = string
  sensitive   = true
  default     = null
}

variable "bot_db_password" {
  description = "Optional explicit bot DB password. Leave null to have Terraform generate one."
  type        = string
  sensitive   = true
  default     = null
}

variable "jwt_secret" {
  description = "Optional explicit JWT secret. Leave null to have Terraform generate one."
  type        = string
  sensitive   = true
  default     = null
}

variable "copilot_llm_api_key" {
  description = "DeepSeek/OpenAI-compatible LLM API key for AI features."
  type        = string
  sensitive   = true
  default     = null
}

variable "copilot_llm_provider" {
  description = "Provider name for Copilot chat. Use openai for DeepSeek/OpenAI-compatible endpoints."
  type        = string
  default     = "openai"
}

variable "copilot_llm_base_url" {
  description = "Base URL for the LLM provider."
  type        = string
  default     = "https://api.deepseek.com/v1"
}

variable "copilot_llm_model" {
  description = "Model name for the LLM provider."
  type        = string
  default     = "deepseek-chat"
}

variable "letsencrypt_email" {
  description = "Email passed to Certbot when requesting certificates."
  type        = string
  default     = "ops@quantgambit.com"
}

variable "swap_size_gb" {
  description = "Swap file size created during bootstrap."
  type        = number
  default     = 8
}

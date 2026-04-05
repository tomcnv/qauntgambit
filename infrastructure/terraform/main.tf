terraform {
  required_version = ">= 1.5.0"

  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["137112412989"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  secret_env_name = var.environment == "production" ? "prod" : (var.environment == "development" ? "dev" : var.environment)
  app_env_secret_name = coalesce(var.app_env_secret_name, "${var.project_name}/${var.environment}/single-ec2/app-env")
  cloudflare_origin_secret_name = coalesce(var.cloudflare_origin_secret_name, "${var.project_name}/${var.environment}/single-ec2/cloudflare-origin")

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "Terraform"
    Owner       = var.owner_email
    Region      = var.aws_region
  }

  resolved_cloudflare_origin_cert_pem = var.cloudflare_origin_certificate_pem != null ? var.cloudflare_origin_certificate_pem : ""
  resolved_cloudflare_origin_key_pem  = var.cloudflare_origin_private_key_pem != null ? var.cloudflare_origin_private_key_pem : ""

  selected_az = coalesce(var.availability_zone, data.aws_availability_zones.available.names[0])

  hostnames = {
    apex      = var.root_domain
    www       = "www.${var.root_domain}"
    dashboard = "dashboard.${var.root_domain}"
    api       = "api.${var.root_domain}"
    bot       = "bot.${var.root_domain}"
  }

  resolved_platform_db_password = coalesce(var.platform_db_password, random_password.platform_db.result)
  resolved_bot_db_password      = coalesce(var.bot_db_password, random_password.bot_db.result)
  resolved_jwt_secret           = coalesce(var.jwt_secret, random_password.jwt.result)

  app_env_secret_string = templatefile("${path.module}/templates/app-env.env.tftpl", {
    environment           = var.environment
    secret_environment    = local.secret_env_name
    auth_mode             = var.auth_mode
    allow_unauthenticated = var.allow_unauthenticated
    jwt_secret            = local.resolved_jwt_secret
    platform_db_user      = var.platform_db_user
    platform_db_password  = local.resolved_platform_db_password
    platform_db_name      = var.platform_db_name
    bot_db_user           = var.bot_db_user
    bot_db_password       = local.resolved_bot_db_password
    bot_db_name           = var.bot_db_name
    core_api_port         = var.core_api_port
    bot_api_port          = var.bot_api_port
    active_exchange       = var.active_exchange
    bybit_demo            = var.bybit_demo
    bybit_testnet         = var.bybit_testnet
    order_updates_demo    = var.order_updates_demo
    orderbook_symbols     = join(",", var.trading_symbols)
    symbols               = join(",", var.trading_symbols)
    root_domain           = var.root_domain
    dashboard_domain      = local.hostnames.dashboard
    api_domain            = local.hostnames.api
    bot_domain            = local.hostnames.bot
    www_domain            = local.hostnames.www
    copilot_llm_provider  = var.copilot_llm_provider
    copilot_llm_api_key   = var.copilot_llm_api_key != null ? var.copilot_llm_api_key : ""
    copilot_llm_base_url  = var.copilot_llm_base_url
    copilot_llm_model     = var.copilot_llm_model
    aws_region            = var.aws_region
  })

  bootstrap_page = <<-HTML
  <!doctype html>
  <html lang="en">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>${var.project_name} bootstrap</title>
      <style>
        body {
          margin: 0;
          font-family: ui-sans-serif, system-ui, sans-serif;
          background: #0f172a;
          color: #e2e8f0;
          display: grid;
          place-items: center;
          min-height: 100vh;
        }
        main {
          width: min(720px, calc(100vw - 48px));
          padding: 32px;
          border-radius: 20px;
          background: rgba(15, 23, 42, 0.92);
          border: 1px solid rgba(148, 163, 184, 0.18);
          box-shadow: 0 24px 80px rgba(15, 23, 42, 0.45);
        }
        h1 { margin-top: 0; }
        code {
          background: rgba(30, 41, 59, 0.95);
          padding: 2px 8px;
          border-radius: 8px;
        }
      </style>
    </head>
    <body>
      <main>
        <h1>${var.project_name} infrastructure is up</h1>
        <p>This EC2 host is reachable and waiting for the application deployment step.</p>
        <p>Connect with SSM and run <code>deploy/single-ec2/deploy.sh</code> from a checkout of this repository.</p>
      </main>
    </body>
  </html>
  HTML
}

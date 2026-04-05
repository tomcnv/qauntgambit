resource "random_password" "platform_db" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "random_password" "bot_db" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "random_password" "jwt" {
  length           = 64
  special          = false
}

resource "aws_secretsmanager_secret" "app_env" {
  count                   = var.manage_app_env_secret ? 1 : 0
  name                    = local.app_env_secret_name
  description             = "Single-EC2 deploy environment file for ${local.name_prefix}"
  recovery_window_in_days = 7

  tags = {
    Name = "${local.name_prefix}-app-env"
    Type = "app-env"
  }
}

resource "aws_secretsmanager_secret_version" "app_env" {
  count         = var.manage_app_env_secret ? 1 : 0
  secret_id     = aws_secretsmanager_secret.app_env[0].id
  secret_string = local.app_env_secret_string
}

resource "aws_secretsmanager_secret" "cloudflare_origin" {
  count                   = var.manage_cloudflare_origin_secret ? 1 : 0
  name                    = local.cloudflare_origin_secret_name
  description             = "Cloudflare origin certificate bundle for ${local.name_prefix}"
  recovery_window_in_days = 7

  tags = {
    Name = "${local.name_prefix}-cloudflare-origin"
    Type = "tls-origin"
  }
}

resource "aws_secretsmanager_secret_version" "cloudflare_origin" {
  count     = var.manage_cloudflare_origin_secret ? 1 : 0
  secret_id = aws_secretsmanager_secret.cloudflare_origin[0].id
  secret_string = jsonencode({
    certificate_pem = local.resolved_cloudflare_origin_cert_pem
    private_key_pem = local.resolved_cloudflare_origin_key_pem
  })

  lifecycle {
    precondition {
      condition     = trimspace(local.resolved_cloudflare_origin_cert_pem) != "" && trimspace(local.resolved_cloudflare_origin_key_pem) != ""
      error_message = "cloudflare_origin_certificate_pem and cloudflare_origin_private_key_pem must be set when manage_cloudflare_origin_secret=true."
    }
  }
}

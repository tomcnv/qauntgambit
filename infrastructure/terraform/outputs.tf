output "instance_id" {
  description = "EC2 instance ID."
  value       = aws_instance.app.id
}

output "instance_public_ip" {
  description = "Public IP of the application host."
  value       = aws_eip.app.public_ip
}

output "instance_public_dns" {
  description = "Public DNS hostname of the EC2 instance."
  value       = aws_instance.app.public_dns
}

output "ssm_start_session_command" {
  description = "Command to open an SSM shell without SSH."
  value       = "aws ssm start-session --target ${aws_instance.app.id} --region ${var.aws_region}"
}

output "route53_zone_id" {
  description = "Route 53 zone hosting quantgambit.com records."
  value       = local.route53_zone_id
}

output "bootstrap_urls" {
  description = "Initial hostnames wired to the EC2 instance."
  value       = local.hostnames
}

output "app_env_secret_name" {
  description = "Secrets Manager secret name for the single-EC2 application environment file."
  value       = var.manage_app_env_secret ? aws_secretsmanager_secret.app_env[0].name : null
}

output "app_env_secret_arn" {
  description = "Secrets Manager secret ARN for the single-EC2 application environment file."
  value       = var.manage_app_env_secret ? aws_secretsmanager_secret.app_env[0].arn : null
}

output "cloudflare_origin_secret_name" {
  description = "Secrets Manager secret name for the Cloudflare origin certificate bundle."
  value       = var.manage_cloudflare_origin_secret ? aws_secretsmanager_secret.cloudflare_origin[0].name : null
}

output "cloudflare_origin_secret_arn" {
  description = "Secrets Manager secret ARN for the Cloudflare origin certificate bundle."
  value       = var.manage_cloudflare_origin_secret ? aws_secretsmanager_secret.cloudflare_origin[0].arn : null
}

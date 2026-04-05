resource "aws_route53_zone" "main" {
  count = var.manage_route53_records && var.create_route53_zone ? 1 : 0
  name  = var.root_domain

  tags = {
    Name = "${local.name_prefix}-zone"
  }
}

locals {
  route53_zone_id = (
    !var.manage_route53_records
    ? null
    : (var.create_route53_zone ? aws_route53_zone.main[0].zone_id : var.existing_route53_zone_id)
  )
}

resource "aws_route53_record" "apex" {
  count   = var.manage_route53_records ? 1 : 0
  zone_id = local.route53_zone_id
  name    = var.root_domain
  type    = "A"
  ttl     = 300
  records = [aws_eip.app.public_ip]

  lifecycle {
    precondition {
      condition     = local.route53_zone_id != null && trimspace(local.route53_zone_id) != ""
      error_message = "existing_route53_zone_id must be set when create_route53_zone is false."
    }
  }
}

resource "aws_route53_record" "www" {
  count   = var.manage_route53_records ? 1 : 0
  zone_id = local.route53_zone_id
  name    = local.hostnames.www
  type    = "A"
  ttl     = 300
  records = [aws_eip.app.public_ip]
}

resource "aws_route53_record" "dashboard" {
  count   = var.manage_route53_records ? 1 : 0
  zone_id = local.route53_zone_id
  name    = local.hostnames.dashboard
  type    = "A"
  ttl     = 300
  records = [aws_eip.app.public_ip]
}

resource "aws_route53_record" "api" {
  count   = var.manage_route53_records ? 1 : 0
  zone_id = local.route53_zone_id
  name    = local.hostnames.api
  type    = "A"
  ttl     = 300
  records = [aws_eip.app.public_ip]
}

resource "aws_route53_record" "bot" {
  count   = var.manage_route53_records ? 1 : 0
  zone_id = local.route53_zone_id
  name    = local.hostnames.bot
  type    = "A"
  ttl     = 300
  records = [aws_eip.app.public_ip]
}

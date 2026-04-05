resource "aws_eip" "app" {
  domain = "vpc"

  tags = {
    Name = "${local.name_prefix}-eip"
  }
}

resource "aws_instance" "app" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.ec2.id]
  iam_instance_profile        = aws_iam_instance_profile.ec2.name
  key_name                    = var.key_name
  monitoring                  = var.enable_detailed_monitoring
  associate_public_ip_address = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
    instance_metadata_tags      = "enabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_size_gb
    iops                  = var.root_volume_iops
    throughput            = var.root_volume_throughput
    delete_on_termination = true
    encrypted             = true
  }

  user_data = templatefile("${path.module}/templates/cloud-init.sh.tftpl", {
    project_name      = var.project_name
    root_domain       = var.root_domain
    www_domain        = local.hostnames.www
    dashboard_domain  = local.hostnames.dashboard
    api_domain        = local.hostnames.api
    bot_domain        = local.hostnames.bot
    letsencrypt_email = var.letsencrypt_email
    swap_size_gb      = var.swap_size_gb
    bootstrap_page    = local.bootstrap_page
    aws_region        = var.aws_region
    app_env_secret_id = var.manage_app_env_secret ? aws_secretsmanager_secret.app_env[0].name : ""
    cloudflare_origin_secret_id = var.manage_cloudflare_origin_secret ? aws_secretsmanager_secret.cloudflare_origin[0].name : ""
  })

  tags = {
    Name = "${local.name_prefix}-app"
    Role = "single-ec2-app"
  }
}

resource "aws_eip_association" "app" {
  allocation_id = aws_eip.app.id
  instance_id   = aws_instance.app.id
}

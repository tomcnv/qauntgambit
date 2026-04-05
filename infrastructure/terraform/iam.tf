locals {
  default_ssm_parameter_arns = [
    "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/${var.environment}/*",
    "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/shared/*",
  ]

  default_secret_arns = [
    "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.project_name}/${var.environment}/*",
    "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.project_name}/shared/*",
    "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:deeptrader/${local.secret_env_name}/*",
  ]

  runtime_ssm_parameter_arns = length(var.ssm_parameter_arns) > 0 ? var.ssm_parameter_arns : local.default_ssm_parameter_arns
  runtime_secret_arns        = length(var.secretsmanager_secret_arns) > 0 ? var.secretsmanager_secret_arns : local.default_secret_arns
  exchange_secret_arns = [
    "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:deeptrader/${local.secret_env_name}/*",
  ]
  deploy_artifact_bucket_arn = "arn:aws:s3:::${var.deploy_artifact_bucket_name}"
  deploy_artifact_object_arn = "arn:aws:s3:::${var.deploy_artifact_bucket_name}/${var.deploy_artifact_prefix}*"
}

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name               = "${local.name_prefix}-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "cloudwatch" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

data "aws_iam_policy_document" "app_runtime" {
  statement {
    sid = "ReadSsmRuntimeConfig"

    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath"
    ]

    resources = local.runtime_ssm_parameter_arns
  }

  statement {
    sid = "ReadSecretsManagerRuntimeConfig"

    actions = [
      "secretsmanager:GetSecretValue"
    ]

    resources = local.runtime_secret_arns
  }

  statement {
    sid = "ManageExchangeSecrets"

    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:UpdateSecret",
      "secretsmanager:PutSecretValue",
      "secretsmanager:DeleteSecret"
    ]

    resources = local.exchange_secret_arns
  }

  statement {
    sid = "CreateExchangeSecrets"

    actions = [
      "secretsmanager:CreateSecret"
    ]

    resources = ["*"]

    condition {
      test     = "StringLike"
      variable = "secretsmanager:Name"
      values   = ["deeptrader/${local.secret_env_name}/*"]
    }
  }

  dynamic "statement" {
    for_each = length(var.kms_key_arns) > 0 ? [1] : []
    content {
      sid = "DecryptRuntimeKeys"

      actions = [
        "kms:Decrypt"
      ]

      resources = var.kms_key_arns
    }
  }

  statement {
    sid = "ReadDeployArtifacts"

    actions = [
      "s3:GetObject"
    ]

    resources = [local.deploy_artifact_object_arn]
  }

  statement {
    sid = "ListDeployArtifacts"

    actions = [
      "s3:ListBucket"
    ]

    resources = [local.deploy_artifact_bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.deploy_artifact_prefix}*"]
    }
  }
}

resource "aws_iam_role_policy" "app_runtime" {
  name   = "${local.name_prefix}-runtime"
  role   = aws_iam_role.ec2.id
  policy = data.aws_iam_policy_document.app_runtime.json
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${local.name_prefix}-ec2-profile"
  role = aws_iam_role.ec2.name
}

# The network: the account's default VPC, and a security group that opens nothing.
#
# There is no inbound rule at all, and no SSH key. The instance is reached through SSM Session
# Manager, which dials out from the instance, so the API is never exposed to the internet and the
# bearer token never crosses it in the clear (docs/adr/0020).

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# The subnet is chosen once, here, and both the server and its disk are pinned to it. Reading the
# availability zone off the instance instead would make the disk depend on the instance, and then
# replacing the instance would replace the disk: exactly what the disk exists to prevent.
data "aws_subnet" "chosen" {
  id = data.aws_subnets.default.ids[0]
}

resource "aws_security_group" "server" {
  name        = "${var.name}-server"
  description = "testhunch server: no inbound, egress only"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.server.id
  description       = "Pulling images, reaching SSM and S3"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ---- secrets -------------------------------------------------------------------------------
# Generated here and kept in Parameter Store, encrypted. They are never written to a file in the
# repository, and `terraform output` shows them only when asked for by name.

resource "random_password" "postgres" {
  length  = 32
  special = false # a URL-safe password: it goes into TESTHUNCH_DATABASE_URL
}

resource "random_password" "api_token" {
  length  = 48
  special = false
}

resource "aws_ssm_parameter" "postgres" {
  name  = "/${var.name}/postgres-password"
  type  = "SecureString"
  value = random_password.postgres.result
}

resource "aws_ssm_parameter" "api_token" {
  name  = "/${var.name}/api-token"
  type  = "SecureString"
  value = random_password.api_token.result
}

# ---- object storage for the raw reports -----------------------------------------------------
# Provisioned and reachable from the instance. Nothing writes to it yet: the API stores results
# in Postgres and keeps no copy of the XML it was sent.

resource "random_id" "bucket" {
  byte_length = 4
}

resource "aws_s3_bucket" "reports" {
  bucket = "${var.name}-reports-${random_id.bucket.hex}"
}

resource "aws_s3_bucket_public_access_block" "reports" {
  bucket                  = aws_s3_bucket.reports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "reports" {
  bucket = aws_s3_bucket.reports.id

  versioning_configuration {
    status = "Enabled"
  }
}

# ---- the instance's identity ----------------------------------------------------------------

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "server" {
  name               = "${var.name}-server"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.server.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "server" {
  statement {
    sid     = "ReadItsOwnSecrets"
    actions = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = [
      aws_ssm_parameter.postgres.arn,
      aws_ssm_parameter.api_token.arn,
      aws_ssm_parameter.image.arn, # not a secret, but read the same way at every boot
    ]
  }

  statement {
    sid       = "DecryptThoseSecrets"
    actions   = ["kms:Decrypt"]
    resources = ["*"] # the account's default SSM key, which has no ARN of its own here

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.region}.amazonaws.com"]
    }
  }

  statement {
    sid       = "WriteRawReports"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.reports.arn}/*"]
  }

  statement {
    sid       = "ListRawReports"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.reports.arn]
  }

  dynamic "statement" {
    # Alertmanager signs its own requests with this role, so no key is kept on the instance.
    for_each = aws_sns_topic.alerts

    content {
      sid       = "RaiseAnAlert"
      actions   = ["sns:Publish"]
      resources = [statement.value.arn]
    }
  }
}

resource "aws_iam_role_policy" "server" {
  name   = "${var.name}-server"
  role   = aws_iam_role.server.id
  policy = data.aws_iam_policy_document.server.json
}

resource "aws_iam_instance_profile" "server" {
  name = "${var.name}-server"
  role = aws_iam_role.server.name
}

# ---- the server ------------------------------------------------------------------------------

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
}

resource "aws_instance" "server" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnet.chosen.id
  vpc_security_group_ids = [aws_security_group.server.id]
  iam_instance_profile   = aws_iam_instance_profile.server.name

  # A public address for egress only: the security group lets nothing in. Without it the instance
  # would need a NAT gateway, which costs more than the instance.
  associate_public_ip_address = true

  user_data_replace_on_change = true
  user_data = templatefile("${path.module}/server.sh.tftpl", {
    region              = var.region
    image_parameter     = aws_ssm_parameter.image.name
    postgres_image      = var.postgres_image
    caddy_image         = var.caddy_image
    prometheus_image    = var.prometheus_image
    alertmanager_image  = var.alertmanager_image
    node_exporter_image = var.node_exporter_image
    metrics_retention   = var.metrics_retention
    alert_email         = var.alert_email
    alerts_topic        = one(aws_sns_topic.alerts[*].arn)
    api_domain          = var.api_domain
    compose_version     = var.compose_version
    postgres_parameter  = aws_ssm_parameter.postgres.name
    api_token_parameter = aws_ssm_parameter.api_token.name
    reports_bucket      = aws_s3_bucket.reports.bucket
  })

  root_block_device {
    volume_size = var.root_volume_gb
    volume_type = "gp3"
    encrypted   = true
  }

  metadata_options {
    http_tokens   = "required" # IMDSv2 only
    http_endpoint = "enabled"
  }

  tags = {
    Name = "${var.name}-server"
  }
}

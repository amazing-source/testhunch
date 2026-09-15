# Deploying: naming an image, and telling the server to go and run it.
#
# The image the server runs is a parameter, not a line in this configuration. Terraform sets its
# first value and then never touches it again, so a deployment and a `terraform apply` cannot
# disagree about what is running (docs/adr/0026).

resource "aws_ssm_parameter" "image" {
  name        = "/${var.name}/image"
  description = "The testhunch image the server runs. Written by deployments, read at every boot."
  type        = "String"
  value       = var.image

  lifecycle {
    # Terraform hands this over after creating it: the deployment workflow owns it from then on.
    # Without this, every apply would silently roll the server back to var.image.
    ignore_changes = [value]
  }
}

# One command, with nothing to pass to it. The deploying identity can ask for this and only this,
# so a stolen deployment token cannot run a shell on the server: the script it triggers is written
# by server.sh.tftpl and lives in this repository.
resource "aws_ssm_document" "deploy" {
  name            = "${var.name}-deploy"
  document_type   = "Command"
  document_format = "YAML"

  content = yamlencode({
    schemaVersion = "2.2"
    description   = "Pull the image named in Parameter Store and restart the stack."
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "deploy"
      inputs = { runCommand = ["/usr/local/bin/testhunch-deploy"] }
    }]
  })
}

# ---- the identity GitHub Actions deploys with -------------------------------------------------
# Nothing is created unless a repository is named: an account should not grow a role that lets a
# third party's workflow in because a default said so.

locals {
  deploys_from_github = var.github_repository != ""
}

resource "aws_iam_openid_connect_provider" "github" {
  count = local.deploys_from_github ? 1 : 0

  url = "https://token.actions.githubusercontent.com"
  # No thumbprint list: AWS itself verifies this provider's certificate chain.
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_assume" {
  count = local.deploys_from_github ? 1 : 0

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github[0].arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # One repository, one branch. A pull request from a fork gets a different subject and is
    # refused by STS before any of this account's permissions are consulted.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

data "aws_iam_policy_document" "deploy" {
  count = local.deploys_from_github ? 1 : 0

  statement {
    sid       = "NameTheImageToRun"
    actions   = ["ssm:PutParameter", "ssm:GetParameter"]
    resources = [aws_ssm_parameter.image.arn]
  }

  statement {
    sid       = "TellTheServerToPullIt"
    actions   = ["ssm:SendCommand"]
    resources = [aws_instance.server.arn, aws_ssm_document.deploy.arn]
  }

  statement {
    sid     = "ReadHowThatWent"
    actions = ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"]
    # A command invocation has no name to grant before the command exists.
    resources = ["*"]
  }
}

resource "aws_iam_role" "deploy" {
  count = local.deploys_from_github ? 1 : 0

  name               = "${var.name}-deploy"
  description        = "Assumed by ${var.github_repository} to deploy: no shell, no other resource."
  assume_role_policy = data.aws_iam_policy_document.github_assume[0].json
}

resource "aws_iam_role_policy" "deploy" {
  count = local.deploys_from_github ? 1 : 0

  name   = "${var.name}-deploy"
  role   = aws_iam_role.deploy[0].id
  policy = data.aws_iam_policy_document.deploy[0].json
}

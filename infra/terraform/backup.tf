# Snapshots of the disk that outlives the server (docs/adr/0032).
#
# ADR 0024 gave the database a volume that survives instance replacement. It survives Terraform, not
# the account: a deleted volume, a corrupted filesystem, or a migration that does the wrong thing
# takes every repository's history with it. That was the last unmitigated risk in this deployment.
#
# Data Lifecycle Manager rather than AWS Backup: it does this one thing, it costs nothing beyond the
# snapshots themselves, and it is a handful of resources instead of a vault, a plan and a selection.

data "aws_iam_policy_document" "dlm_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["dlm.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dlm" {
  name               = "${var.name}-dlm"
  assume_role_policy = data.aws_iam_policy_document.dlm_assume.json
}

resource "aws_iam_role_policy_attachment" "dlm" {
  role = aws_iam_role.dlm.name
  # The managed policy for this exact service role: it can snapshot and delete snapshots, nothing
  # else. Writing it by hand would be a longer way to say the same thing, less well maintained.
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}

resource "aws_dlm_lifecycle_policy" "data" {
  # Letters, digits, spaces, hyphens and underscores only: DLM refuses anything else, and it refuses
  # it at apply time. `terraform validate` cannot see this, since the rule belongs to the service.
  description        = "Daily snapshots of the ${var.name} data volume"
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["VOLUME"]

    # By tag rather than by id, which is what DLM offers. The tag comes from the volume resource, so
    # a volume replaced by Terraform is still the one being snapshotted.
    target_tags = {
      Name = aws_ebs_volume.data.tags["Name"]
    }

    schedule {
      name = "daily"

      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        # DLM starts within an hour of this time, so it is a window and not an appointment. Chosen
        # in the quiet hours of the Paris region, which is where the server is (docs/adr/0020).
        times = [var.snapshot_time_utc]
      }

      retain_rule {
        count = var.snapshot_retention
      }

      # A snapshot nobody can identify is a snapshot nobody restores from.
      copy_tags = true
    }
  }
}

variable "snapshot_retention" {
  description = "How many daily snapshots of the data volume to keep."
  type        = number
  default     = 7
}

variable "snapshot_time_utc" {
  description = "When the daily snapshot window opens, UTC, as DLM writes it: HH:MM."
  type        = string
  default     = "03:00"

  validation {
    condition     = can(regex("^([01][0-9]|2[0-3]):[0-5][0-9]$", var.snapshot_time_utc))
    error_message = "snapshot_time_utc must be HH:MM in 24-hour UTC, for instance 03:00."
  }
}

# The disk that outlives the server (docs/adr/0024).
#
# Anything in the instance's user data replaces the instance, and until this existed that took the
# database with it. It also took Caddy's certificates, so every replacement asked Let's Encrypt for
# a new one, against a weekly limit on duplicates. This volume is its own resource: Terraform
# detaches it, replaces the instance, and attaches it back.

resource "aws_ebs_volume" "data" {
  availability_zone = data.aws_subnet.chosen.availability_zone
  size              = var.data_volume_gb
  type              = "gp3"
  encrypted         = true

  tags = {
    Name = "${var.name}-data"
  }

  lifecycle {
    # The history of every repository that uses this deployment lives here. Replacing this volume
    # is not something a plan should ever do quietly; destroying the stack on purpose still works.
    prevent_destroy = true
  }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf" # what the API calls it; the instance sees an NVMe device
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.server.id

  # Replacing the instance means detaching first, and detaching a mounted filesystem from a running
  # instance either hangs or is forced, which is how filesystems get corrupted. This leaves the
  # detaching to the termination that follows: the attachment simply leaves the state, the instance
  # goes away with the volume released, and the next instance attaches it back.
  skip_destroy = true
}

variable "data_volume_gb" {
  description = "The disk holding Postgres and Caddy's certificates, kept across replacements."
  type        = number
  default     = 20
}

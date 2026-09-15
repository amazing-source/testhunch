variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "eu-west-3" # Paris: the data stays in the EU
}

variable "name" {
  description = "Prefix for the name of every resource, so one account can hold several stacks."
  type        = string
  default     = "testhunch"
}

variable "instance_type" {
  description = <<-EOT
    The one server. x86, not Graviton: the published image is linux/amd64 only, because
    .github/workflows/release.yml builds without a `platforms:` list. An arm64 instance would
    pull an image it cannot run, and the failure would only show in the container logs.
  EOT
  type        = string
  default     = "t3.small"

  validation {
    condition     = !startswith(var.instance_type, "t4g.") && !startswith(var.instance_type, "m7g.")
    error_message = "Graviton needs a multi-architecture image; the published one is amd64 only."
  }
}

variable "image" {
  description = "The published image to run. Pinned to an exact version, never :latest."
  type        = string
  default     = "ghcr.io/amazing-source/testhunch:0.3.0"
}

variable "postgres_image" {
  type    = string
  default = "postgres:18"
}

variable "root_volume_gb" {
  description = "The root disk, which also holds the Postgres volume."
  type        = number
  default     = 20
}

variable "compose_version" {
  description = "Docker Compose, pinned: the instance downloads this exact release at first boot."
  type        = string
  default     = "v2.32.4"
}

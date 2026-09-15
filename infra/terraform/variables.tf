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
    The one server. x86, not Graviton: the published image is linux/amd64 only, because neither
    .github/workflows/ci.yml nor release.yml builds with a `platforms:` list. An arm64 instance
    would pull an image it cannot run, and the failure would only show in the container logs.
  EOT
  type        = string
  default     = "t3.small"

  validation {
    condition     = !startswith(var.instance_type, "t4g.") && !startswith(var.instance_type, "m7g.")
    error_message = "Graviton needs a multi-architecture image; the published one is amd64 only."
  }
}

variable "image" {
  description = <<-EOT
    The image the server starts on, and only that: after the stack exists, deployments name the
    image in Parameter Store and Terraform stops looking at it (docs/adr/0026). Pinned to a tag
    that cannot move: a released version, or the `sha-<commit>` that .github/workflows/ci.yml
    publishes for every commit of main that passed.
  EOT
  type        = string
  default     = "ghcr.io/amazing-source/testhunch:0.4.0"

  validation {
    # A moving tag would leave no way to say which commit the server is running.
    condition     = !endswith(var.image, ":latest") && !endswith(var.image, ":main")
    error_message = "Pin the image to a version or to a sha- tag, not to a tag that moves."
  }
}

variable "github_repository" {
  description = <<-EOT
    The repository allowed to deploy, as `owner/name`. Empty means no deployment identity is
    created at all: a role that lets someone else's workflow into this account should never be a
    default. Only its `main` branch is trusted, and only to deploy.
  EOT
  type        = string
  default     = ""

  validation {
    condition     = var.github_repository == "" || length(split("/", var.github_repository)) == 2
    error_message = "Write it as owner/name, or leave it empty."
  }
}

variable "postgres_image" {
  type    = string
  default = "postgres:18"
}

variable "caddy_image" {
  description = "The reverse proxy, used only when api_domain is set."
  type        = string
  default     = "caddy:2-alpine"
}

variable "prometheus_image" {
  type    = string
  default = "prom/prometheus:v3.14.0"
}

variable "alertmanager_image" {
  description = "Used only when alert_email is set: without an address there is nobody to tell."
  type        = string
  default     = "prom/alertmanager:v0.34.0"
}

variable "node_exporter_image" {
  description = "The machine itself: what Prometheus cannot see from inside a container."
  type        = string
  default     = "prom/node-exporter:v1.12.1"
}

variable "metrics_retention" {
  description = "How long Prometheus keeps its samples. It shares the data disk with Postgres."
  type        = string
  default     = "30d"
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

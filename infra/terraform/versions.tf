# One server for testhunch, on AWS (docs/adr/0020). Everything here is destroyed by
# `terraform destroy`: there is no resource outside this state, and none with a retention policy.

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "testhunch"
      ManagedBy = "terraform"
    }
  }
}

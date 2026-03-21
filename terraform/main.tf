terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Local backend — no S3 state bucket needed for dev
  # To use remote state, replace with:
  # backend "s3" {
  #   bucket = "your-terraform-state-bucket"
  #   key    = "rhythmcloud/terraform.tfstate"
  #   region = "eu-north-1"
  # }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

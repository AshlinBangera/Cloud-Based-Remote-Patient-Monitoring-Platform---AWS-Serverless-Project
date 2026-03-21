variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "eu-north-1"
}

variable "aws_profile" {
  description = "AWS CLI profile to use"
  type        = string
  default     = "rhythmcloud"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "project" {
  description = "Project name prefix for all resources"
  type        = string
  default     = "rhythmcloud"
}

variable "raw_events_bucket" {
  description = "S3 bucket containing raw telemetry events (created by SAM)"
  type        = string
}

variable "athena_results_bucket" {
  description = "S3 bucket for Athena query results"
  type        = string
}

variable "glue_crawler_schedule" {
  description = "Cron schedule for the Glue crawler (UTC)"
  type        = string
  default     = "cron(0 2 * * ? *)"
}

variable "athena_data_scan_limit_mb" {
  description = "Per-query data scan limit in MB (cost control)"
  type        = number
  default     = 1024
}

variable "lakeformation_admin_arn" {
  description = "IAM ARN to grant Lake Formation admin access (your user ARN)"
  type        = string
}

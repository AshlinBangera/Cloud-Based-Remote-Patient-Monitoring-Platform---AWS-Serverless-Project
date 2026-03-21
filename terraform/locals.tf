locals {
  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
    Repository  = "Cloud-Based-Remote-Patient-Monitoring-Platform---AWS-Serverless-Project"
  }
}

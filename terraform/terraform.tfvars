# RhythmCloud Terraform — Dev environment variables
# ─────────────────────────────────────────────────
# Fill in the values marked with <REPLACE> before running terraform apply

aws_region  = "eu-north-1"
aws_profile = "rhythmcloud"
environment = "dev"
project     = "rhythmcloud"

# S3 bucket created by SAM — already deployed
raw_events_bucket = "rhythmcloud-raw-events-503644381734-dev"

# S3 bucket for Athena query results — same bucket, different prefix
athena_results_bucket = "rhythmcloud-raw-events-503644381734-dev"

# Run daily at 02:00 UTC
glue_crawler_schedule = "cron(0 2 * * ? *)"

# 1GB per-query limit — keeps you safely on free tier
athena_data_scan_limit_mb = 1024

# Your IAM user ARN — Lake Formation admin
# Get it by running: aws sts get-caller-identity --query Arn --output text --profile rhythmcloud
lakeformation_admin_arn = "arn:aws:iam::503644381734:user/rhythmcloud-cli"

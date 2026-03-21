output "glue_database_name" {
  description = "Glue Data Catalog database name"
  value       = aws_glue_catalog_database.rhythmcloud.name
}

output "glue_crawler_name" {
  description = "Glue crawler name — run manually with: aws glue start-crawler --name <value>"
  value       = aws_glue_crawler.telemetry.name
}

output "glue_etl_job_name" {
  description = "Glue ETL job name — run manually with: aws glue start-job-run --job-name <value>"
  value       = aws_glue_job.json_to_parquet.name
}

output "parquet_bucket" {
  description = "S3 bucket storing Parquet-converted events"
  value       = aws_s3_bucket.parquet.bucket
}

output "athena_workgroup" {
  description = "Athena workgroup name — use this in the Athena console"
  value       = aws_athena_workgroup.rhythmcloud.name
}

output "athena_named_queries" {
  description = "Saved Athena query IDs — visible in the Athena console under Saved queries"
  value = {
    transmission_success_rate = aws_athena_named_query.transmission_success_rate.id
    abnormal_events           = aws_athena_named_query.abnormal_events.id
    adherence_trend           = aws_athena_named_query.adherence_trend.id
    sync_reliability          = aws_athena_named_query.sync_reliability.id
    heatmap_aggregation       = aws_athena_named_query.heatmap_aggregation.id
  }
}

output "account_id" {
  description = "AWS account ID"
  value       = data.aws_caller_identity.current.account_id
}

output "region" {
  description = "AWS region"
  value       = data.aws_region.current.name
}

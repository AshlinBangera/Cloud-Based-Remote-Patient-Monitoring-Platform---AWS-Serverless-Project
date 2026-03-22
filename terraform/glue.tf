# ─────────────────────────────────────────────────────────────────────────────
# AWS Glue — Data Catalog, Crawler, and ETL Job
#
# The Glue Crawler runs daily, crawls the raw S3 event archive,
# auto-discovers the JSON schema and Hive-style partitions, and
# updates the Glue Data Catalog so Athena always has the latest schema.
#
# The ETL job converts raw JSON → Parquet for 10x cheaper Athena queries.
# ─────────────────────────────────────────────────────────────────────────────

# ── Glue Data Catalog Database ────────────────────────────────────────────────
resource "aws_glue_catalog_database" "rhythmcloud" {
  name        = "${var.project}_${var.environment}"
  description = "RhythmCloud cardiac telemetry data catalog — ${var.environment}"

  tags = local.common_tags
}

# ── IAM Role for Glue Crawler and ETL ────────────────────────────────────────
resource "aws_iam_role" "glue" {
  name               = "${var.project}-glue-role-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "glue_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com", "lakeformation.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_s3" {
  name = "${var.project}-glue-s3-${var.environment}"
  role = aws_iam_role.glue.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadRawEvents"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = [
          "arn:aws:s3:::${var.raw_events_bucket}",
          "arn:aws:s3:::${var.raw_events_bucket}/*",
        ]
      },
      {
        Sid    = "WriteParquet"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:DeleteObject",
          "s3:ListBucket",
        ]
        Resource = [
          aws_s3_bucket.parquet.arn,
          "${aws_s3_bucket.parquet.arn}/*",
        ]
      },
      {
        Sid    = "WriteAthenaResults"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket",
        ]
        Resource = [
          "arn:aws:s3:::${var.athena_results_bucket}",
          "arn:aws:s3:::${var.athena_results_bucket}/*",
        ]
      },
    ]
  })
}

# ── Glue Crawler ──────────────────────────────────────────────────────────────
# Crawls raw JSON events in S3, auto-discovers schema and partitions,
# and populates the Glue Data Catalog table automatically.
resource "aws_glue_crawler" "telemetry" {
  name          = "${var.project}-telemetry-crawler-${var.environment}"
  role          = aws_iam_role.glue.arn
  database_name = aws_glue_catalog_database.rhythmcloud.name
  description   = "Crawls raw cardiac telemetry events from S3"
  schedule      = var.glue_crawler_schedule

  s3_target {
    path = "s3://${var.raw_events_bucket}/events/"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  configuration = jsonencode({
    Version = 1.0
    CrawlerOutput = {
      Partitions = { AddOrUpdateBehavior = "InheritFromTable" }
    }
    Grouping = {
      TableGroupingPolicy = "CombineCompatibleSchemas"
    }
  })

  tags = local.common_tags
}

# ── S3 Bucket for Parquet output ──────────────────────────────────────────────
resource "aws_s3_bucket" "parquet" {
  bucket        = "${var.project}-parquet-${data.aws_caller_identity.current.account_id}-${var.environment}"
  force_destroy = true
  tags          = local.common_tags
}

resource "aws_s3_bucket_versioning" "parquet" {
  bucket = aws_s3_bucket.parquet.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "parquet" {
  bucket = aws_s3_bucket.parquet.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "parquet" {
  bucket                  = aws_s3_bucket.parquet.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── Glue ETL Job ──────────────────────────────────────────────────────────────
# Converts raw JSON events → optimised Parquet format.
# Parquet is columnar — Athena only reads the columns needed,
# making queries 5–10x faster and 10x cheaper ($0.50/TB vs $5/TB).
resource "aws_glue_job" "json_to_parquet" {
  name         = "${var.project}-json-to-parquet-${var.environment}"
  role_arn     = aws_iam_role.glue.arn
  description  = "Converts raw JSON telemetry events to Parquet for Athena"
  glue_version = "4.0"
  worker_type  = "G.1X"
  number_of_workers = 2

  command {
    name            = "glueetl"
    script_location = "s3://${var.raw_events_bucket}/glue-scripts/json_to_parquet.py"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--job-bookmark-option"              = "job-bookmark-enable"
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--SOURCE_BUCKET"                    = var.raw_events_bucket
    "--TARGET_BUCKET"                    = aws_s3_bucket.parquet.bucket
    "--GLUE_DATABASE"                    = aws_glue_catalog_database.rhythmcloud.name
    "--ENVIRONMENT"                      = var.environment
    "--TempDir"                          = "s3://${var.raw_events_bucket}/glue-temp/"
  }

  execution_property {
    max_concurrent_runs = 1
  }

  tags = local.common_tags
}

# ── Glue ETL Script (uploaded to S3) ─────────────────────────────────────────
resource "aws_s3_object" "etl_script" {
  bucket  = var.raw_events_bucket
  key     = "glue-scripts/json_to_parquet.py"
  content = <<-PYTHON
import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.dynamicframe import DynamicFrame

args = getResolvedOptions(sys.argv, [
    'JOB_NAME', 'SOURCE_BUCKET', 'TARGET_BUCKET',
    'GLUE_DATABASE', 'ENVIRONMENT'
])

sc      = SparkContext()
glueCtx = GlueContext(sc)
spark   = glueCtx.spark_session
job     = Job(glueCtx)
job.init(args['JOB_NAME'], args)

source_path = f"s3://{args['SOURCE_BUCKET']}/events/"
target_path = f"s3://{args['TARGET_BUCKET']}/events/"

dyf = glueCtx.create_dynamic_frame.from_options(
    connection_type = "s3",
    connection_options = {
        "paths": [source_path],
        "recurse": True,
        "groupFiles": "inPartition",
        "groupSize": "104857600"
    },
    format = "json",
    transformation_ctx = "read_json"
)

if dyf.count() == 0:
    job.commit()
    raise SystemExit(0)

numeric_fields = [
    "heartRate", "spo2", "systolicBP",
    "diastolicBP", "batteryLevel", "signalStrength"
]

resolved = ResolveChoice.apply(
    dyf,
    specs = [(f, "cast:double") for f in numeric_fields]
)

sink = glueCtx.getSink(
    path                = target_path,
    connection_type     = "s3",
    updateBehavior      = "UPDATE_IN_DATABASE",
    compression         = "snappy",
    enableUpdateCatalog = True,
    transformation_ctx  = "write_parquet"
)

sink.setCatalogInfo(
    catalogDatabase  = args['GLUE_DATABASE'],
    catalogTableName = "telemetry_events_parquet"
)
sink.setFormat("glueparquet")
sink.writeFrame(resolved)
job.commit()
  PYTHON

  tags = local.common_tags
}

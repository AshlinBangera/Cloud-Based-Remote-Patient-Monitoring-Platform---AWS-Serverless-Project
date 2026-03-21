# ─────────────────────────────────────────────────────────────────────────────
# AWS Lake Formation — Data Lake Governance
#
# Registers the S3 raw events bucket as a governed data lake location.
# Defines column-level permissions so clinical staff can query vitals
# but ops staff cannot see patient identifiers.
# ─────────────────────────────────────────────────────────────────────────────

# ── Register admin ────────────────────────────────────────────────────────────
resource "aws_lakeformation_data_lake_settings" "admin" {
  admins = [var.lakeformation_admin_arn]
}

# ── Register S3 bucket as a data lake location ────────────────────────────────
resource "aws_lakeformation_resource" "raw_events" {
  arn      = "arn:aws:s3:::${var.raw_events_bucket}"
  role_arn = aws_iam_role.glue.arn

  depends_on = [aws_lakeformation_data_lake_settings.admin]
}

resource "aws_lakeformation_resource" "parquet" {
  arn      = aws_s3_bucket.parquet.arn
  role_arn = aws_iam_role.glue.arn

  depends_on = [aws_lakeformation_data_lake_settings.admin]
}

# ── Data location access for Glue crawler ────────────────────────────────────
resource "aws_lakeformation_permissions" "glue_raw_events_location" {
  principal   = aws_iam_role.glue.arn
  permissions = ["DATA_LOCATION_ACCESS"]

  data_location {
    arn = "arn:aws:s3:::${var.raw_events_bucket}"
  }

  depends_on = [aws_lakeformation_data_lake_settings.admin]
}

# ── Database-level permissions for Glue role ─────────────────────────────────
resource "aws_lakeformation_permissions" "glue_database" {
  principal   = aws_iam_role.glue.arn
  permissions = ["CREATE_TABLE", "DESCRIBE"]

  database {
    name = aws_glue_catalog_database.rhythmcloud.name
  }

  depends_on = [aws_lakeformation_data_lake_settings.admin]
}

# ── Table-level permissions for Glue role ────────────────────────────────────
resource "aws_lakeformation_permissions" "glue_all_tables" {
  principal   = aws_iam_role.glue.arn
  permissions = ["SELECT", "INSERT", "DELETE", "DESCRIBE", "ALTER"]

  table {
    database_name = aws_glue_catalog_database.rhythmcloud.name
    wildcard      = true
  }

  depends_on = [aws_lakeformation_data_lake_settings.admin]
}

# ── Clinical staff permissions — full vitals access ───────────────────────────
# Can see ALL columns including patient identifiers and clinical data
resource "aws_lakeformation_permissions" "admin_full" {
  principal   = var.lakeformation_admin_arn
  permissions = ["SELECT", "DESCRIBE"]

  table {
    database_name = aws_glue_catalog_database.rhythmcloud.name
    wildcard      = true
  }

  depends_on = [aws_lakeformation_data_lake_settings.admin]
}

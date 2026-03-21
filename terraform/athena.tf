# ─────────────────────────────────────────────────────────────────────────────
# Amazon Athena — Workgroup and query results configuration
#
# The workgroup enforces a per-query data scan limit to prevent
# accidentally expensive queries. Free tier: first 1TB scanned/month free.
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_athena_workgroup" "rhythmcloud" {
  name        = "${var.project}-${var.environment}"
  description = "RhythmCloud Athena workgroup — ${var.environment}"
  state       = "ENABLED"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.athena_data_scan_limit_mb * 1024 * 1024

    result_configuration {
      output_location = "s3://${var.athena_results_bucket}/athena-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }

  tags = local.common_tags
}

# ── Athena named queries — save the 5 analysis queries as saved queries ───────
resource "aws_athena_named_query" "transmission_success_rate" {
  name        = "${var.project}-transmission-success-rate"
  workgroup   = aws_athena_workgroup.rhythmcloud.id
  database    = aws_glue_catalog_database.rhythmcloud.name
  description = "Daily transmission success rate with 7-day rolling average"

  query = <<-SQL
    SELECT
        CONCAT(year, '-', month, '-', day)   AS event_date,
        COUNT(*)                              AS total_events,
        COUNT(CASE WHEN transmissionStatus = 'success' THEN 1 END) AS successful,
        COUNT(CASE WHEN transmissionStatus = 'failed'  THEN 1 END) AS failed,
        ROUND(
            100.0 * COUNT(CASE WHEN transmissionStatus = 'success' THEN 1 END)
            / NULLIF(COUNT(*), 0), 2
        ) AS success_rate_pct
    FROM ${aws_glue_catalog_database.rhythmcloud.name}.events
    WHERE CAST(year AS INT) >= YEAR(CURRENT_DATE - INTERVAL '30' DAY)
    GROUP BY year, month, day
    ORDER BY event_date DESC;
  SQL
}

resource "aws_athena_named_query" "abnormal_events" {
  name        = "${var.project}-abnormal-events"
  workgroup   = aws_athena_workgroup.rhythmcloud.id
  database    = aws_glue_catalog_database.rhythmcloud.name
  description = "Abnormal event counts by patient and type"

  query = <<-SQL
    SELECT
        patientId,
        COUNT(*) AS total_events,
        SUM(CASE WHEN heartRate < 50 OR heartRate > 130
                   OR spo2 < 90
                   OR transmissionStatus = 'failed'
             THEN 1 ELSE 0 END) AS abnormal_count,
        ROUND(AVG(heartRate), 1) AS avg_heart_rate,
        ROUND(AVG(spo2), 1)      AS avg_spo2
    FROM ${aws_glue_catalog_database.rhythmcloud.name}.events
    WHERE CAST(year AS INT) >= YEAR(CURRENT_DATE - INTERVAL '7' DAY)
    GROUP BY patientId
    ORDER BY abnormal_count DESC;
  SQL
}

resource "aws_athena_named_query" "adherence_trend" {
  name        = "${var.project}-adherence-trend"
  workgroup   = aws_athena_workgroup.rhythmcloud.id
  database    = aws_glue_catalog_database.rhythmcloud.name
  description = "Per-patient daily adherence score with 7-day rolling average"

  query = <<-SQL
    SELECT
        patientId,
        CONCAT(year, '-', month, '-', day) AS event_date,
        COUNT(*) AS total_events,
        COUNT(CASE WHEN transmissionStatus = 'success'
                    AND syncStatus = 'synced'
                    AND heartRate BETWEEN 50 AND 130
                    AND spo2 >= 90
               THEN 1 END) AS adherent_events,
        ROUND(
            100.0 * COUNT(CASE WHEN transmissionStatus = 'success'
                               AND syncStatus = 'synced'
                               AND heartRate BETWEEN 50 AND 130
                               AND spo2 >= 90
                          THEN 1 END)
            / NULLIF(COUNT(*), 0), 2
        ) AS adherence_score_pct
    FROM ${aws_glue_catalog_database.rhythmcloud.name}.events
    WHERE CAST(year AS INT) >= YEAR(CURRENT_DATE - INTERVAL '30' DAY)
    GROUP BY patientId, year, month, day
    ORDER BY patientId, event_date DESC;
  SQL
}

resource "aws_athena_named_query" "sync_reliability" {
  name        = "${var.project}-sync-reliability"
  workgroup   = aws_athena_workgroup.rhythmcloud.id
  database    = aws_glue_catalog_database.rhythmcloud.name
  description = "Device health status, signal quality and failure patterns"

  query = <<-SQL
    SELECT
        deviceId,
        patientId,
        CONCAT(year, '-', month, '-', day) AS event_date,
        COUNT(*) AS total_events,
        COUNT(CASE WHEN syncStatus = 'synced' THEN 1 END) AS synced_count,
        COUNT(CASE WHEN syncStatus = 'failed' THEN 1 END) AS sync_failed_count,
        ROUND(
            100.0 * COUNT(CASE WHEN syncStatus = 'synced' THEN 1 END)
            / NULLIF(COUNT(*), 0), 2
        ) AS sync_reliability_pct,
        ROUND(AVG(signalStrength), 1) AS avg_signal_dbm,
        ROUND(AVG(batteryLevel),  1) AS avg_battery_pct
    FROM ${aws_glue_catalog_database.rhythmcloud.name}.events
    WHERE CAST(year AS INT) >= YEAR(CURRENT_DATE - INTERVAL '7' DAY)
    GROUP BY deviceId, patientId, year, month, day
    ORDER BY sync_reliability_pct ASC;
  SQL
}

resource "aws_athena_named_query" "heatmap_aggregation" {
  name        = "${var.project}-heatmap-aggregation"
  workgroup   = aws_athena_workgroup.rhythmcloud.id
  database    = aws_glue_catalog_database.rhythmcloud.name
  description = "7x7 cardiac event heatmap by day of week and 3-hour bucket"

  query = <<-SQL
    SELECT
        DATE_FORMAT(DATE_PARSE(CONCAT(year,'-',month,'-',day),'%Y-%m-%d'), '%a') AS day_of_week,
        CASE
            WHEN CAST(hour AS INT) BETWEEN 0  AND 2  THEN '00'
            WHEN CAST(hour AS INT) BETWEEN 3  AND 5  THEN '03'
            WHEN CAST(hour AS INT) BETWEEN 6  AND 8  THEN '06'
            WHEN CAST(hour AS INT) BETWEEN 9  AND 11 THEN '09'
            WHEN CAST(hour AS INT) BETWEEN 12 AND 14 THEN '12'
            WHEN CAST(hour AS INT) BETWEEN 15 AND 17 THEN '15'
            ELSE '18'
        END AS time_bucket,
        COUNT(*) AS total_events,
        SUM(CASE WHEN heartRate < 50 OR heartRate > 130 OR spo2 < 90
             THEN 1 ELSE 0 END) AS abnormal_events
    FROM ${aws_glue_catalog_database.rhythmcloud.name}.events
    WHERE CAST(year AS INT) >= YEAR(CURRENT_DATE - INTERVAL '30' DAY)
    GROUP BY 1, 2
    ORDER BY 1, 2;
  SQL
}

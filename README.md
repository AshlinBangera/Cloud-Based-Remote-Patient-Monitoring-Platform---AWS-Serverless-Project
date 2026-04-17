# RhythmCloud — Cloud-Based Remote Patient Monitoring Platform

> **Where real-time rhythm meets life-changing care.**

A production-grade, fully serverless AWS platform that ingests cardiac IoT telemetry, detects abnormal events, computes real-time clinical KPIs, triggers instant clinical alerts, tracks alert response times, scores patient risk, powers a live operational dashboard, and delivers Athena-powered analytics from a governed data lake.

[![AWS SAM](https://img.shields.io/badge/AWS-SAM-orange?logo=amazonaws)](https://aws.amazon.com/serverless/sam/)
[![Terraform](https://img.shields.io/badge/IaC-Terraform-7B42BC?logo=terraform)](https://terraform.io)
[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://python.org)
[![DynamoDB](https://img.shields.io/badge/Amazon-DynamoDB-blue?logo=amazondynamodb)](https://aws.amazon.com/dynamodb/)
[![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub_Actions-black?logo=githubactions)](https://github.com/features/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## Live Dashboard Preview

![RhythmCloud Dashboard](docs/dashboard-preview.png)

The dashboard displays real-time data from AWS — transmission success rates, cardiac event heatmaps, patient adherence, risk scores, active clinical alerts, SpO2 trending, device health, and a live event feed — all powered by serverless APIs with patient filtering and time range selection.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [AWS Services Used](#aws-services-used)
- [Project Structure](#project-structure)
- [API Endpoints](#api-endpoints)
- [Data Models](#data-models)
- [Setup & Deployment](#setup--deployment)
- [CI/CD Pipeline](#cicd-pipeline)
- [Real-Time Alerting](#real-time-alerting)
- [Alert Response Time Tracking](#alert-response-time-tracking)
- [Patient Risk Scoring](#patient-risk-scoring)
- [Terraform Data Layer](#terraform-data-layer)
- [Athena Analytics Page](#athena-analytics-page)
- [Dashboard Features](#dashboard-features)
- [Data Simulator](#data-simulator)
- [CloudWatch Metrics & Alarms](#cloudwatch-metrics--alarms)
- [Resume Bullets](#resume-bullets)

---

## Overview

RhythmCloud simulates a healthcare platform where wearable cardiac devices send telemetry to the cloud every few seconds. The system:

- **Ingests** patient vitals (heart rate, SpO2, blood pressure, battery level, signal strength) via a REST API
- **Detects** abnormal clinical events — tachycardia, bradycardia, hypoxia, hypertensive crises, transmission failures
- **Alerts** clinical staff in real time via SNS email notifications within seconds of abnormal event detection
- **Tracks** alert response times from detection to clinician acknowledgement, publishing `AlertResponseTimeSeconds` to CloudWatch
- **Scores** each patient's composite risk (0–100) across 5 weighted clinical factors using pure Python logic
- **Computes** rolling KPIs per patient — transmission success rate, sync reliability, adherence score, abnormal event frequency
- **Archives** every raw event to S3 with Hive-style partitioning
- **Transforms** raw JSON → Parquet via AWS Glue ETL job (10x cheaper Athena queries, Snappy compressed)
- **Governs** the data lake with AWS Lake Formation — registered locations, column-level access control
- **Analyses** historical data via 5 Athena-powered query types visualised in a dedicated analytics page
- **Exposes** 13 REST API endpoints powering a live operational dashboard
- **Provisions** compute with SAM and data infrastructure with Terraform — dual IaC strategy
- **Deploys** automatically via GitHub Actions CI/CD on every push to `main`, with manual staging promotion

### Business Context

Remote patient monitoring is a fast-growing segment of digital health. This project simulates the backend of a platform used by clinical teams to monitor cardiac patients outside hospital settings. The architecture mirrors real-world production systems used by companies like Medtronic, iRhythm, and Philips Healthcare.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          CLIENT LAYER                                 │
│                                                                       │
│   IoT Cardiac Simulator          Dashboard + Analytics Page          │
│   (scripts/simulate_data.py)     (frontend/rpm-dashboard.html)       │
│                                  (frontend/analytics.html)           │
└──────────────┬───────────────────────────────┬───────────────────────┘
               │ POST /events                  │ GET /dashboard/* /analytics
               ▼                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                   Amazon API Gateway (REST API) — 13 routes           │
└──────────┬────────────────────────────────────┬──────────────────────┘
           │                                    │
           ▼                                    ▼
┌──────────────────────┐           ┌────────────────────────────────────┐
│  Lambda: Ingest      │           │  Lambda: Read APIs (×13)           │
│  1. Validate payload │           │  get_dashboard_kpis                │
│  2. Write DynamoDB   │           │  get_sync_frequency                │
│  3. Archive → S3     │           │  get_adherence / get_heatmap       │
│  4. Detect abnormal  │           │  get_vitals_trend                  │
│  5. Publish SNS alert│           │  get_recent_events                 │
│  6. Write AlertsTable│           │  get_analytics (Athena)            │
│  7. Publish CW metric│           │  get_patient_risk/alerts/summary   │
└──────────┬───────────┘           │  get_patient_events                │
           │                       │  acknowledge_alert                 │
           ▼                       └────────────┬───────────────────────┘
┌──────────────────────┐                        │
│  DynamoDB (6 tables) │◄───────────────────────┘
│  TelemetryEvents     │
│  PatientSummaries    │
│  DashboardAggregates │
│  RecentEvents        │
│  DeviceStatus        │
│  Alerts              │
└──────────┬───────────┘
           │ DynamoDB Streams
           ▼
┌──────────────────────┐     ┌──────────────────────┐
│  Lambda: KPI Engine  │────►│  CloudWatch           │
│  · TX success rate   │     │  Custom Metrics       │
│  · Sync reliability  │     │  + 5 Alarms           │
│  · Adherence score   │     └──────────────────────┘
│  · Abnormal freq     │
│  · Vitals trend      │     ┌──────────────────────┐
│  · Heatmap matrix    │────►│  Amazon SNS           │
└──────────┬───────────┘     │  Clinical alert email │
           │                 └──────────────────────┘
           │ S3 archive (Hive partitioned JSON)
           ▼
┌────────────────────────┐   ┌──────────────────────────────────────┐
│  Amazon S3             │   │  Terraform — Data Layer               │
│  Raw Events (JSON)     │──►│  Glue Crawler → schema discovery     │
│  year/month/day/hour/  │   │  Glue ETL job → Parquet (Snappy)     │
│  patientId/eventId.json│   │  Lake Formation permissions           │
│                        │   └──────────────────┬───────────────────┘
│  S3 Parquet Bucket     │◄─────────────────────┘
└────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  Amazon Athena                        │
│  Workgroup: rhythmcloud-dev           │
│  Database: rhythmcloud_dev            │
│  5 saved named queries                │
│  GET /analytics Lambda endpoint       │
│  frontend/analytics.html              │
└──────────────────────────────────────┘
```

---

## AWS Services Used

| Service | Purpose |
|---------|---------|
| **AWS Lambda** | 14 functions — ingest, KPI processor, alerting, risk scoring, Athena analytics, 9 dashboard read APIs |
| **Amazon API Gateway** | REST API with CORS, throttling — 13 routes |
| **Amazon DynamoDB** | 6 tables — events, summaries, aggregates, recent events, device status, alerts |
| **Amazon S3** | Raw event archival (JSON, Hive partitioned) + Parquet data lake output |
| **Amazon SNS** | Real-time clinical alert email notifications |
| **Amazon CloudWatch** | Custom metrics namespace `RhythmCloud`, 5 alarms, response time tracking |
| **AWS Glue** | Data Catalog, daily crawler (auto-discovers schema + partitions), ETL job (JSON → Parquet) |
| **Amazon Athena** | SQL analytics over S3 data lake — workgroup with 1GB cost controls, 5 saved named queries |
| **AWS Lake Formation** | Data lake governance — registered S3 locations, column-level permissions |
| **AWS SQS** | Dead letter queue for KPI processor stream failures |
| **AWS IAM** | Least-privilege roles scoped to exact resources |
| **AWS SAM** | IaC for compute layer — Lambda, API Gateway, DynamoDB, SNS, SQS, CloudWatch alarms |
| **Terraform** | IaC for data layer — Glue, Athena, Lake Formation, S3 Parquet bucket (20 resources) |
| **AWS X-Ray** | Distributed tracing on all Lambda functions |
| **GitHub Actions** | CI/CD pipeline — lint, test, deploy to dev, manual staging promotion |

---

## Project Structure

```
rhythmcloud/
├── .github/workflows/
│   └── deploy.yml              # CI/CD — lint & test → dev → staging (manual)
├── template.yaml               # SAM IaC — Lambda, API Gateway, DynamoDB, SNS, SQS
├── samconfig.toml              # SAM config for dev / staging / prod
├── requirements.txt
│
├── frontend/
│   ├── rpm-dashboard.html      # Live operational dashboard (13 API endpoints)
│   └── analytics.html          # Athena-powered analytics page (5 query types)
│
├── src/
│   ├── handlers/
│   │   ├── ingest_event.py             # POST /events
│   │   ├── kpi_processor.py            # DynamoDB Streams trigger
│   │   ├── acknowledge_alert.py        # POST /alerts/{alertId}/acknowledge
│   │   ├── get_analytics.py            # GET /analytics (Athena queries)
│   │   ├── get_patient_risk.py         # GET /patients/{patientId}/risk
│   │   ├── get_patient_alerts.py       # GET /patients/{patientId}/alerts
│   │   ├── get_dashboard_kpis.py       # GET /dashboard/kpis
│   │   ├── get_sync_frequency.py       # GET /dashboard/sync-frequency
│   │   ├── get_adherence.py            # GET /dashboard/adherence
│   │   ├── get_vitals_trend.py         # GET /dashboard/vitals-trend
│   │   ├── get_heatmap.py              # GET /dashboard/heatmap
│   │   ├── get_recent_events.py        # GET /dashboard/recent-events
│   │   ├── get_patient_summary.py      # GET /patients/{patientId}/summary
│   │   └── get_patient_events.py       # GET /patients/{patientId}/events
│   │
│   ├── services/
│   │   ├── dynamodb_service.py         # All DynamoDB read/write operations
│   │   ├── s3_service.py               # S3 event archival
│   │   ├── aggregation_service.py      # KPI computation logic
│   │   ├── alerting_service.py         # SNS alert publishing + alert record creation
│   │   ├── alerts_db_service.py        # Alerts table CRUD + response time tracking
│   │   ├── risk_scoring_service.py     # Patient risk scoring engine
│   │   └── metrics_service.py          # CloudWatch custom metrics
│   │
│   └── utils/
│       ├── validator.py                # Schema validation (types, ranges, enums)
│       ├── response.py                 # Standardised API response builders
│       └── time_buckets.py             # Timestamp → heatmap bucket mapping
│
├── terraform/                  # Terraform — data infrastructure layer
│   ├── main.tf                 # AWS provider, backend config
│   ├── variables.tf            # environment, region, IAM ARN inputs
│   ├── locals.tf               # common name prefix + tags
│   ├── glue.tf                 # Glue DB, crawler, ETL job, IAM role, Parquet S3 bucket
│   ├── athena.tf               # Workgroup (1GB limit) + 5 named queries
│   ├── lake_formation.tf       # Data lake registration + column-level permissions
│   ├── outputs.tf              # Glue DB name, workgroup, Parquet bucket
│   └── terraform.tfvars        # Dev environment values
│
├── tests/
│   ├── conftest.py
│   └── test_ingestion.py       # 14 unit tests (moto mocks — no real AWS)
│
├── scripts/
│   └── simulate_data.py        # Cardiac IoT telemetry simulator (5 patients)
│
├── sql/                        # Standalone Athena SQL files
│   ├── create_table.sql
│   ├── transmission_success_rate.sql
│   ├── abnormal_events.sql
│   ├── adherence_trend.sql
│   ├── sync_reliability.sql
│   └── heatmap_aggregation.sql
│
└── events/
    ├── sample_event.json
    └── sample_abnormal_event.json
```

---

## API Endpoints

Base URL: `https://<api-id>.execute-api.eu-north-1.amazonaws.com/dev`

### Ingest

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/events` | Ingest telemetry event — triggers SNS alert if abnormal |

### Alerts

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/alerts/{alertId}/acknowledge` | Clinician acknowledges alert, records response time |
| `GET`  | `/patients/{patientId}/alerts`  | Alert history with avg/fastest/slowest response times |

### Analytics (Athena-powered)

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/analytics?query=population\|transmission\|adherence\|abnormal\|sync&days=7\|14\|30` | Runs Athena SQL against the Glue data lake, returns chart-ready results |

### Dashboard

| Method | Path | Widget | Refresh |
|--------|------|--------|---------|
| `GET` | `/dashboard/kpis`          | TX gauge + sync card + abnormal counter | 10s |
| `GET` | `/dashboard/sync-frequency` | Device Sync Frequency line chart | 30s |
| `GET` | `/dashboard/adherence`      | Patient Adherence bar chart | 60s |
| `GET` | `/dashboard/vitals-trend`   | Patient Vitals Trending chart | 30s |
| `GET` | `/dashboard/heatmap`        | Cardiac Event Heatmap | 60s |
| `GET` | `/dashboard/recent-events`  | Recent Device Events table | 5s |

### Patient

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/patients/{patientId}/risk`    | Composite risk score (0–100) with clinical recommendations |
| `GET` | `/patients/{patientId}/summary` | Full KPI summary for one patient |
| `GET` | `/patients/{patientId}/events`  | Paginated event history (`?limit=50`) |

---

## Data Models

### DynamoDB Tables

| Table | PK | SK | Purpose |
|-------|----|----|---------|
| `TelemetryEvents` | `patientId` | `eventId` | All raw telemetry events (TTL 90d), Streams enabled |
| `PatientSummaries` | `patientId` | — | Rolling KPIs per patient |
| `DashboardAggregates` | `metricType` | `periodKey` | Pre-computed chart data (TTL 48h) |
| `RecentEvents` | `RECENT` | `timestamp#eventId` | Ring-buffer for events table (TTL 24h) |
| `DeviceStatus` | `deviceId` | — | Latest device snapshot |
| `Alerts` | `alertId` | — | Clinical alerts with response time tracking; GSI on `patientId` |

### Abnormal Event Detection

| Field | Condition |
|-------|-----------|
| `heartRate` | `< 50 bpm` (bradycardia) or `> 130 bpm` (tachycardia) |
| `spo2` | `< 90%` (hypoxia) |
| `systolicBP` | `> 180 mmHg` (hypertensive crisis) |
| `batteryLevel` | `< 20%` |
| `transmissionStatus` | `"failed"` |
| `syncStatus` | `"failed"` |

---

## Setup & Deployment

### Prerequisites

```bash
brew install awscli
brew tap aws/tap && brew install aws-sam-cli
brew tap hashicorp/tap && brew install hashicorp/tap/terraform
brew install python@3.11
```

### Configure AWS credentials

```bash
aws configure --profile rhythmcloud
# Region: eu-north-1
export AWS_PROFILE=rhythmcloud
```

### Deploy compute layer (SAM)

```bash
git clone https://github.com/AshlinBangera/Cloud-Based-Remote-Patient-Monitoring-Platform---AWS-Serverless-Project.git
cd Cloud-Based-Remote-Patient-Monitoring-Platform---AWS-Serverless-Project

sam build --config-env dev && sam deploy --config-env dev
```

### Deploy data layer (Terraform)

```bash
cd terraform

# Get your IAM ARN for terraform.tfvars
aws sts get-caller-identity --query Arn --output text --profile rhythmcloud

terraform init
terraform plan
terraform apply
```

### Run the Glue crawler (first time)

```bash
aws glue start-crawler \
  --name rhythmcloud-telemetry-crawler-dev \
  --profile rhythmcloud --region eu-north-1

# Verify Glue table was created
aws glue get-tables --database-name rhythmcloud_dev \
  --profile rhythmcloud --region eu-north-1 \
  --query 'TableList[*].Name'
```

### Test the API

```bash
BASE="https://<your-api-id>.execute-api.eu-north-1.amazonaws.com/dev"

curl -X POST $BASE/events -H "Content-Type: application/json" -d @events/sample_event.json
curl $BASE/dashboard/kpis
curl "$BASE/analytics?query=population&days=30"
curl $BASE/patients/P001/risk
```

### Run the dashboard locally

```bash
cd frontend
python3 -m http.server 8080
# Dashboard:  http://localhost:8080/rpm-dashboard.html
# Analytics:  http://localhost:8080/analytics.html
```

### Tear down

```bash
aws cloudformation delete-stack --stack-name rhythmcloud-dev --region eu-north-1
cd terraform && terraform destroy
```

---

## CI/CD Pipeline

Every push to `main` automatically runs the full pipeline. Staging promotion is manual.

```
Push to main
    ↓
Lint & Test (~30s)
  · flake8 syntax check
  · pytest 14 unit tests (moto mocks — no real AWS calls)
    ↓
Deploy to Dev (~90s)
  · sam build --config-env dev
  · sam deploy --config-env dev
  · Smoke test: POST /events → assert HTTP 200/201
  · Smoke test: GET /dashboard/kpis → assert HTTP 200
    ↓
[Manual: GitHub Actions → Run workflow → promote_to_staging=true]
    ↓
Deploy to Staging
  · Isolated rhythmcloud-staging stack
  · INFO logging, 60-day data retention
  · confirm_changeset=true — never auto-deploys
```

Setup: add `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` as GitHub repository secrets.

---

## Real-Time Alerting

When the ingest Lambda detects an abnormal cardiac event, it immediately publishes a structured alert to SNS, delivering an email to clinicians within seconds.

| Alert Type | Trigger |
|------------|---------|
| TACHYCARDIA | HR > 130 bpm |
| BRADYCARDIA | HR < 50 bpm |
| HYPOXIA | SpO2 < 90% |
| HYPERTENSIVE_CRISIS | Systolic BP > 180 mmHg |
| BATTERY_CRITICAL | Battery < 20% |
| TRANSMISSION_FAILURE | transmissionStatus = "failed" |
| SYNC_FAILURE | syncStatus = "failed" |

Email subject format: `[HIGH] RhythmCloud Alert — Tachycardia — Patient P002`

Configure: set `ClinicalAlertEmail` in `samconfig.toml` and confirm the AWS subscription email.

---

## Alert Response Time Tracking

Every alert is written to `AlertsTable` with `status: ACTIVE`. When a clinician acknowledges it, the system records the delta and publishes `AlertResponseTimeSeconds` to CloudWatch.

```bash
# 1. Ingest an abnormal event — creates alert record
curl -X POST $BASE/events -d '{"heartRate":155,...}'

# 2. Get the alertId
curl $BASE/patients/P001/alerts

# 3. Acknowledge — see response time in reply
curl -X POST $BASE/alerts/<alertId>/acknowledge \
  -d '{"acknowledgedBy":"Dr. Smith"}'
# → {"responseTimeSec": 274, "responseTimeLabel": "4m 34s"}
```

The dashboard also provides a one-click Acknowledge button in the Active Alerts panel — no terminal required.

---

## Patient Risk Scoring

Pure Python scoring engine reads the last 50 events per patient and outputs a composite 0–100 risk score with clinical recommendations. No ML framework needed.

| Factor | Weight | What it measures |
|--------|--------|-----------------|
| Abnormal event frequency | 30% | % of recent events with abnormal vitals |
| Vitals trend direction | 25% | Are HR/SpO2/BP moving toward or away from normal? |
| Transmission reliability | 20% | Failure rate of device transmissions |
| Device health | 15% | Battery level + signal strength |
| SpO2 average | 10% | Average oxygen saturation |

| Score | Level | Action |
|-------|-------|--------|
| 0–24 | LOW 🟢 | Routine monitoring |
| 25–49 | MEDIUM 🟡 | Schedule clinical review |
| 50–74 | HIGH 🟠 | Urgent review within 2–4 hours |
| 75–100 | CRITICAL 🔴 | Immediate intervention required |

---

## Terraform Data Layer

Data infrastructure is provisioned separately from SAM — the dual-IaC pattern used in real production teams. SAM owns compute; Terraform owns data.

### Resources provisioned (20 total)

| Resource | Name | Purpose |
|----------|------|---------|
| `aws_glue_catalog_database` | `rhythmcloud_dev` | Central metadata store for all tables |
| `aws_glue_crawler` | `rhythmcloud-telemetry-crawler-dev` | Daily S3 crawl — auto-discovers schema and partitions |
| `aws_glue_job` | `rhythmcloud-json-to-parquet-dev` | ETL — raw JSON → Parquet, Snappy compressed, 10x cheaper queries |
| `aws_s3_bucket` | `rhythmcloud-parquet-*` | Columnar output bucket, versioned, AES-256 |
| `aws_athena_workgroup` | `rhythmcloud-dev` | 1GB per-query scan limit, SSE results, CloudWatch metrics |
| `aws_athena_named_query` ×5 | — | Saved SQL queries visible in Athena console |
| `aws_lakeformation_resource` ×2 | — | Raw events + Parquet buckets registered as data lake |
| `aws_lakeformation_permissions` ×4 | — | Column-level access control for Glue and Lambda roles |
| `aws_iam_role` | `rhythmcloud-glue-role-dev` | Least-privilege role for Glue crawler and ETL |

### Deploy

```bash
cd terraform
terraform init && terraform plan && terraform apply
```

### Run the Glue ETL job manually

```bash
aws glue start-job-run \
  --job-name rhythmcloud-json-to-parquet-dev \
  --profile rhythmcloud --region eu-north-1
```

---

## Athena Analytics Page

`frontend/analytics.html` is a standalone analytics page backed by the `GET /analytics` Lambda, which runs parameterised Athena SQL queries against the Glue data catalog and returns chart-ready JSON.

### 5 analysis types

| Query | Visualisation |
|-------|--------------|
| Population Health | 7 KPI cards — avg HR, SpO2 range, TX success %, clinical alerts, battery, patient count |
| Transmission | Daily TX success rate line chart with 90% target line + breakdown table |
| Adherence | Bar chart + per-patient progress bars coloured green/amber/red |
| Abnormal Events | Bar chart + doughnut chart + patient detail table with avg HR/SpO2 |
| Device Sync | Reliability table with battery/signal + grouped bar chart per device |

Each result shows data scanned (KB), execution time, and workgroup at the bottom. Time window is selectable: 7, 14, or 30 days.

```bash
# Example API calls
curl "$BASE/analytics?query=population&days=30"
curl "$BASE/analytics?query=transmission&days=14"
curl "$BASE/analytics?query=sync&days=7"
```

---

## Dashboard Features

`frontend/rpm-dashboard.html` — the main operational dashboard, entirely client-side, polling 13 live AWS API endpoints.

### Control toolbar
- **Patient selector pills** — All / P001–P005. Filters the events table, highlights the selected patient's adherence bar, and switches the vitals chart to per-patient raw events
- **Time range pills** — 1h / 6h / 24h / 7d. Maps to data point limits sent as `?limit=` query params on chart endpoints

### KPI section
- Transmission Success Rate gauge with 20-point historical sparkline and trend arrow
- Device Sync Reliability card — operational status, latency, failure count
- Device Sync Frequency line chart
- Abnormal Event Frequency counter (last 24h)
- AWS Pipeline animation — IoT → API Gateway → Lambda → DynamoDB → S3 → CloudWatch → SNS

### Clinical section
- SpO2 Trending chart — purple line chart with red 90% threshold reference line
- Device Health grid — battery progress bar + signal status per device, updates every 30s

### Risk & Alerts section
- **Patient Risk Scores panel** — all 5 patients with colour-coded risk bars (green/amber/orange/red); click any row to open the patient drill-down panel
- **Alert Response Time KPI** — avg / fastest / slowest acknowledgement times across all patients
- **Active Alerts panel** — all unacknowledged alerts sorted by recency with inline Acknowledge button
- **Notification bell** — badge showing unread alert count, shakes red when a new alert fires

### Patient drill-down panel
Slides in from the right when clicking any patient ID in the risk panel or events table:
- Risk score banner — colour-coded with score, level, and top contributing factor
- Latest vitals grid — HR, SpO2, SBP, DBP, Battery, Last Seen — red borders on abnormal values
- Clinical recommendations from the risk scoring engine
- Alert history — last 5 alerts with type, time elapsed, and acknowledgement time
- Recent events — last 8 events with per-row HR / SpO2 / SBP readings

---

## Data Simulator

```bash
# Standard — 200 events across 5 patients over 6 hours
python3 scripts/simulate_data.py --patients 5 --events 40 --hours-back 6

# High-stress — more abnormal events to trigger alerts
python3 scripts/simulate_data.py --patients 5 --events 20 --abnormal-rate 0.4

# Preview without hitting the API
python3 scripts/simulate_data.py --dry-run --events 5
```

| Patient | Name | Condition |
|---------|------|-----------|
| P001 | Alice Brennan | Atrial fibrillation |
| P002 | Brian Doyle | Heart failure |
| P003 | Catherine Murphy | Hypertension |
| P004 | David O'Sullivan | Arrhythmia |
| P005 | Eleanor Walsh | Coronary artery disease |

Simulated abnormal events: tachycardia (130–180 bpm), bradycardia (30–49 bpm), hypertensive crisis (SBP 185–230), hypoxia (SpO2 82–89%), transmission failures (8%), sync failures (6%), battery critical (<20%).

---

## CloudWatch Metrics & Alarms

Custom metrics published to the `RhythmCloud` namespace:

| Metric | Unit | Description |
|--------|------|-------------|
| `TotalEvents` | Count | Every ingested telemetry event |
| `AbnormalEvents` | Count | Events exceeding clinical thresholds |
| `TransmissionFailures` | Count | Failed device transmissions |
| `SyncFailures` | Count | Failed device syncs |
| `TransmissionSuccessRate` | Percent | Rolling TX success rate per batch |
| `AdherenceScore` | Percent | Average patient adherence |
| `AlertResponseTimeSeconds` | Seconds | Time from alert detection to acknowledgement |

| Alarm | Threshold | Trigger |
|-------|-----------|---------|
| High abnormal event rate | ≥10 events / 5 min | Clinical review required |
| Low transmission success | <90% over 2 periods | Device investigation |
| Low adherence score | <70% hourly avg | Patient outreach |
| Ingest Lambda errors | ≥5 errors / 3 min | Engineering alert |
| KPI processor DLQ depth | ≥1 message | Stream processing failure |

---

## Resume Bullets

- **Designed and deployed a production-grade serverless remote patient monitoring platform on AWS**, processing cardiac IoT telemetry through a Lambda → DynamoDB Streams → KPI aggregation pipeline with zero server management

- **Built a real-time clinical alerting system using Amazon SNS**, triggering structured email notifications to clinicians within seconds of abnormal cardiac events — tachycardia, bradycardia, hypoxia, hypertensive crisis — with full patient vitals in the alert body

- **Implemented end-to-end alert response time tracking**, recording detection-to-acknowledgement deltas per alert and publishing `AlertResponseTimeSeconds` to CloudWatch; clinicians acknowledge directly from the dashboard without any terminal access

- **Engineered a patient risk scoring engine in pure Python** computing composite 0–100 risk scores from 5 weighted clinical factors across each patient's last 50 telemetry events, with colour-coded levels and auto-generated clinical recommendations

- **Built an AWS Glue data pipeline** converting Hive-partitioned S3 JSON events to Snappy-compressed Parquet, reducing Athena query costs by 10x, with automated daily schema discovery via a Glue crawler updating the Glue Data Catalog

- **Governed a production data lake using AWS Lake Formation**, registering S3 locations and enforcing column-level access control permissions separating clinical from operational roles

- **Delivered Athena-powered analytics** via a dedicated analytics page backed by a Lambda endpoint that executes 5 parameterised SQL queries — population health, transmission trends, adherence scoring, abnormal event analysis, device sync reliability — visualised with Chart.js

- **Implemented dual Infrastructure as Code** — AWS SAM for the serverless compute layer (Lambda, API Gateway, DynamoDB, SNS) and Terraform for the data layer (Glue, Athena, Lake Formation — 20 resources), mirroring the separation of concerns used in real production engineering teams

- **Architected a real-time clinical data API** using API Gateway + Lambda serving 13 REST endpoints backed by pre-computed DynamoDB aggregates for sub-100ms dashboard response times

- **Built a GitHub Actions CI/CD pipeline** with automated lint, 14 moto-mocked unit tests, `sam build`, `sam deploy`, live smoke tests on two endpoints, and manual staging promotion via `workflow_dispatch`

- **Developed a feature-rich operational dashboard** with patient selector, time range filter, SpO2 trending, device health grid, patient drill-down panel, notification bell with alert badge, and an active alerts panel with inline acknowledgement — all connected to live AWS APIs

---

MIT — see [LICENSE](LICENSE)

---

*Built with AWS Lambda · DynamoDB · S3 · API Gateway · SNS · CloudWatch · Glue · Athena · Lake Formation · SAM · Terraform · GitHub Actions*

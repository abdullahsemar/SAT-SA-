# Supervisory Review Platform — 120-Second Demonstration Script

**Target Duration**: 110–120 seconds  
**Objective**: Demonstrate end-to-end supervisory assessment workflow: from reported operational metrics to explainable machine hypothesis, alternative hypotheses, submodular portfolio inspection, human decision recording, and cryptographic offline export.

---

## Timeline & Narration Script

### [00:00 – 00:20] Step 1: Reported Performance vs Underlying Claims
- **Action**: Open web application at `http://127.0.0.1:5173`. Show Dashboard / Entity Overview.
- **Narrative**:
  > *"We begin on the supervisory dashboard for Entity SEC-ORG-001. At first glance, the organization reports a stellar 98.5% SLA adherence and near-zero critical backlogs. But our supervisory analytics engine reconciles these surface claims against raw ticket timestamps, detection telemetry, and shift logs."*

---

### [00:20 – 00:40] Step 2: Explained Concern with Concrete Lineage
- **Action**: Click on Analysis Run and expand finding `POL-ESC-002` (*Delayed Critical Escalation*).
- **Narrative**:
  > *"The machine identifies a severe deviation: an escalation delay of over 140 minutes on a confirmed ransomware alert. Notice that this is not an autonomous black-box verdict. The platform presents the concrete telemetry evidence, exact policy rule violated, and uncertainty bounds, clearly framing it as a supervisory hypothesis."*

---

### [00:40 – 00:55] Step 3: Legitimate Alternative Hypotheses & Unknowns
- **Action**: Highlight the *Alternative Explanations* and *Missing Evidence* cards in the Finding Detail panel.
- **Narrative**:
  > *"Critically, the system actively checks for benign explanations—such as outsourced MSSP triage or external API downtime—and lists missing forensic artifacts like raw PCAP captures or endpoint telemetry. This protects examiners from premature confirmation bias."*

---

### [00:55 – 01:20] Step 4: Diversified Review Portfolio (Submodular Knapsack)
- **Action**: Navigate to the **Review Queue** tab.
- **Narrative**:
  > *"Rather than drowning the examiner in dozens of redundant alerts, our submodular knapsack optimizer selects a balanced, budget-constrained portfolio. Within a 60-minute examiner budget, it allocates targeted high-risk findings alongside benign controls and exploratory edge cases to maximize marginal diagnostic information."*

---

### [01:20 – 01:40] Step 5: Examiner Deliberation & Immutability
- **Action**: Click on a finding, select `additional_evidence_required`, enter rationale *"Request firewall flow logs"*, and submit. Show the new audit decision record.
- **Narrative**:
  > *"The examiner exercises supervisory judgment. The machine's finding is strictly immutable. Human decisions are written to an append-only audit trail with cryptographic versioning. Here, the examiner requests supplementary firewall PCAP captures without altering the original machine detection."*

---

### [01:40 – 02:00] Step 6: Frozen Assessment Snapshot & Offline Export
- **Action**: Navigate to **Reports & Exports**. Click **Generate Frozen Report**. Show preview and download the Bundle.
- **Narrative**:
  > *"Finally, we generate a frozen assessment snapshot. The resulting package contains self-contained printable HTML, raw JSON, and a SHA-256 checksum manifest. Even if operational databases update or models retrain, this supervisory report remains cryptographically immutable and 100% reproducible offline without internet access."*

---

## Real Upload-to-Export Workflow: Reproduction Steps

To execute the real end-to-end workflow manually against the live application:

### Step 1: Initialize Database & Run Backend
In PowerShell terminal 1:
```powershell
# Set database URI to a test database if not using default
$env:DATABASE_URL = "sqlite:///storage/sat_sa_demo.db"
.\.venv\Scripts\python.exe -m alembic upgrade head

# Launch FastAPI backend on port 8000
.\.venv\Scripts\python.exe -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

### Step 2: Launch Frontend
In PowerShell terminal 2:
```powershell
npm --prefix apps/web run dev -- --port 5173
```

### Step 3: Authenticate & Obtain Bearer Token
```powershell
$authResponse = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/auth/token" -ContentType "application/x-www-form-urlencoded" -Body "username=examiner1&password=Password123!"
$token = $authResponse.access_token
$headers = @{ "Authorization" = "Bearer $token" }
```

### Step 4: Create Submission with Manifest
```powershell
$subBody = @{
    entity_id = "ORG-DEMO-01"
    title = "Q3 Supervised SOC Ingestion"
    reporting_period_start = "2026-07-01T00:00:00Z"
    reporting_period_end = "2026-09-30T23:59:59Z"
    manifest = @{
        files = @(
            @{ filename = "tickets.csv"; record_type = "tickets"; source_system = "ticketing_prod"; declared_count = 2 }
            @{ filename = "escalations.csv"; record_type = "escalations"; source_system = "pagerduty_prod"; declared_count = 1 }
        )
    }
} | ConvertTo-Json -Depth 5

$submission = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/submissions" -Headers $headers -ContentType "application/json" -Body $subBody
$subId = $submission.id
```

### Step 5: Upload Actual CSV File Bytes & Commit
```powershell
# Upload tickets.csv
$ticketsCsv = "ticket_id,title,priority,created_at,resolved_at,root_cause`nCASE-101,Ransomware,P1,2026-08-01T10:00:00Z,2026-08-01T14:00:00Z,Phishing credential compromise`nCASE-102,Phish Test,P3,2026-08-02T10:00:00Z,2026-08-02T11:00:00Z,Security drill"
$ticketsBytes = [System.Text.Encoding]::UTF8.GetBytes($ticketsCsv)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/submissions/$subId/files?filename=tickets.csv&record_type=tickets&source_system=ticketing_prod" -Headers $headers -ContentType "application/octet-stream" -Body $ticketsBytes

# Upload escalations.csv
$escCsv = "escalation_id,ticket_id,escalated_at,escalated_to`nESC-01,CASE-102,2026-08-02T10:15:00Z,tier2_oncall"
$escBytes = [System.Text.Encoding]::UTF8.GetBytes($escCsv)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/submissions/$subId/files?filename=escalations.csv&record_type=escalations&source_system=pagerduty_prod" -Headers $headers -ContentType "application/octet-stream" -Body $escBytes

# Commit submission (locks files against mutation)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/submissions/$subId/commit" -Headers $headers
```

### Step 6: Create & Execute Assessment Run
```powershell
$runBody = @{ submission_id = $subId } | ConvertTo-Json
$run = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/analysis/runs" -Headers $headers -ContentType "application/json" -Body $runBody
$runId = $run.id

# Execute assessment detectors
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/analysis/runs/$runId/execute" -Headers $headers

# Retrieve findings
$findings = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/findings?run_id=$runId" -Headers $headers
```

### Step 7: Submodular Review Portfolio & Examiner Decision
```powershell
# Generate diversified 60-minute review portfolio
$portBody = @{ budget_minutes = 60 } | ConvertTo-Json
$portfolio = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/review/portfolio/$runId" -Headers $headers -ContentType "application/json" -Body $portBody

# Record examiner finding determination
$findingId = $findings[0].id
$decBody = @{
    decision = "potential_concern"
    rationale = "Confirmed 4-hour delay on critical incident with unevidenced escalation."
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/review/findings/$findingId/decision" -Headers $headers -ContentType "application/json" -Body $decBody
```

### Step 8: Generate Frozen Assessment Report & Download Offline Package
```powershell
# Generate frozen snapshot report
$repBody = @{
    submission_id = $subId
    run_id = $runId
    title = "Supervisory Assessment Report - Q3"
} | ConvertTo-Json
$report = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/reports/generate" -Headers $headers -ContentType "application/json" -Body $repBody
$reportId = $report.id

# Download standalone offline package (HTML, JSON, and ZIP bundle)
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/reports/$reportId/download?format=html" -Headers $headers -OutFile "supervisory_report.html"
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/reports/$reportId/download?format=json" -Headers $headers -OutFile "supervisory_report.json"
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/reports/$reportId/download?format=zip" -Headers $headers -OutFile "supervisory_report.zip"
```

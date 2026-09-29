# SAT-SA Supervisory Rule Cards (Task 2)

This document formalizes the five bounded supervisory rule families implemented in the Supervisory Analytics Tool for SOC Assessment (SAT-SA). Each card defines the rule obligation, evidence requirements, bounded evaluation logic, and supervisory evidence states.

---

## 1. Rule POL-INV-001: Case Investigation Quality and Closure Evidence

- **Obligation ID**: `POL-INV-001`
- **Family**: Investigation Evidence Completeness
- **Target Objects**: Cases (`cases` table linked to `investigation_actions`)
- **Policy Standard**: Cases closed or resolved must demonstrate substantive investigation actions and all policy-required artifacts (e.g., triage notes, forensic triage, host isolation, root cause disposition).

### Evaluation Logic
- **Substantive Evidence vs Placeholder**: A nonempty `root_cause` field alone does NOT prove compliance. "UNKNOWN", whitespace, or placeholder text does not count as substantive evidence.
- **Required Artifact Completeness**: If `root_cause` exists but other policy-mandated artifacts (e.g. required triage actions or hashes) are missing from sufficiently complete evidence, the detector triggers `potential_concern`.
- **Missing or Incomplete Action Sources**: If investigation action logs are missing, unsubmitted, or incomplete, the detector issues `insufficient_evidence` rather than penalizing the case.
- **Fast Closures**: Closures occurring under the duration threshold (e.g., $< 1$ minute) are **NOT penalized** if required artifacts and investigation actions are adequately evidenced.
- **Independence of Obligations**: Investigation completeness is evaluated independently from escalation timeliness.

### Evidence States
| State | Trigger Condition |
| :--- | :--- |
| `supported` | All applicable policy-required closure artifacts and investigation actions are verified. |
| `potential_concern` | Case closed with missing required artifacts or placeholder/unsubstantiated disposition in complete evidence. |
| `insufficient_evidence` | Investigation action telemetry or required artifact sources omitted or incomplete. |
| `not_applicable` | Case remains open or an approved exception excuses specific requirements. |

---

## 2. Rule POL-ESC-002: Escalation Policy Compliance and Timeliness

- **Obligation ID**: `POL-ESC-002`
- **Family**: Timely Escalation Evidence
- **Target Objects**: High and Critical Cases (`cases` linked to `escalations`)
- **Policy Standard**: High and Critical cases must have escalation actions initiated within prescribed SLA windows (e.g., Critical: 30m, High: 2h).

### Evaluation Logic
- **Authoritative Source vs Arbitrary Logs**: Simply uploading an unrelated action log does NOT constitute complete escalation evidence. The detector verifies whether an authoritative escalation export (e.g., PagerDuty) exists, its export scope covers the case and window, and its declared records match parsed counts.
- **Early Resolution**: If a case was resolved and closed before the escalation deadline (`closed_at <= due_at`), the case never matured into an overdue escalation breach.
- **Snapshot Cutoff Awareness**: If `created_at + sla > cutoff_time`, the obligation was not yet due at the frozen submission cutoff date. It is **never declared overdue**.
- **Missing vs Verified Absence**:
  - Overdue obligation + missing/incomplete escalation source $\rightarrow$ `insufficient_evidence`.
  - Overdue obligation + verified complete authoritative source + no escalation $\rightarrow$ `potential_concern`.
- **Policy Exceptions**: Active, approved exceptions covering the case or entity within the validity window excuse the escalation requirement (`not_applicable` or exempted).

### Evidence States
| State | Trigger Condition |
| :--- | :--- |
| `supported` | Distinct escalation action verified within policy SLA window. |
| `potential_concern` | Applicable overdue escalation verified absent from complete authoritative source without valid exception. |
| `insufficient_evidence` | Authoritative escalation export omitted, incomplete, or out of scope. |
| `not_applicable` | Action due date exceeds submission cutoff window, case resolved before SLA, or valid exception applies. |

---

## 3. Rule POL-COV-003: Critical Asset Monitoring Coverage and Inventory Freshness

- **Obligation ID**: `POL-COV-003`
- **Family**: Critical Asset Monitoring Coverage
- **Target Objects**: Critical Assets (`assets` table linked to `alerts` and telemetry)
- **Policy Standard**: Active critical assets must maintain active monitoring telemetry and sensor reporting.

### Evaluation Logic
- **Healthy Silence**: An asset generating 0 alerts is **NOT flagged** as an unmonitored gap if its telemetry agent status is `HEALTHY` and heartbeat is fresh. Absence of alerts does not equate to absence of monitoring.
- **Broken Sensor / Coverage Gap**: If an active critical asset has telemetry status `UNHEALTHY`, `DISCONNECTED`, or `MISSING`, it triggers `potential_concern`.
- **Missing Telemetry**: If heartbeat and agent status fields are omitted, the evaluation suspends verdict with `insufficient_evidence`.

### Evidence States
| State | Trigger Condition |
| :--- | :--- |
| `supported` | Active critical asset with healthy telemetry agent and heartbeats (with or without alerts). |
| `potential_concern` | Active critical asset with confirmed sensor failure (`UNHEALTHY` / `DISCONNECTED`). |
| `insufficient_evidence` | Asset inventory present but telemetry status and heartbeats omitted. |

---

## 4. Rule POL-KPI-004: Supervisory KPI Claim Reconciliation

- **Obligation ID**: `POL-KPI-004`
- **Family**: Reported Claim versus Observed Population
- **Target Objects**: Self-reported claims (`reported_claims` table reconciled against distinct `cases`)
- **Policy Standard**: Self-reported SLA compliance claims ($C$) must be reconciled against the observable population ($n$) within bounded mathematical uncertainty intervals without inventing fallback data.

### Intake Semantics & Claim Hygiene
- **No Claims Source Declared**: Produces NO attributed finding. Absence of an optional self-reported claim is never treated as a compliance failure.
- **Declared-but-Missing Source**: Preserves the evidence gap as `insufficient_evidence`. Never manufactures a claim value (e.g. no invented 98% or fictional `SELF-REPORTED-SLA`).
- **Malformed Claims**: Non-numeric values or percentages $<0$ or $>100$ are rejected/quarantined. Never clamped into range or defaulted.
- **Out-of-Scope Claims**: Valid claims outside the entity/period/metric scope are tracked in `excluded_claims` with explicit exclusion reasons; never compared against unrelated populations.

### Bounded Uncertainty Mathematical Model
$$\text{Lower Bound} = \frac{y}{n} \times 100\%$$
$$\text{Upper Bound} = \frac{y + u}{n} \times 100\%$$
Where:
- $n$ = total distinct eligible cases evaluated in the period
- $y$ = count of verified compliant distinct cases
- $u$ = count of indeterminate/unknown outcome cases (e.g. open cases not yet due at cutoff)

### Disproof Logic
- **Contradiction**: Requires the valid upper bound $(y + u) / n$ to strictly fall below the claimed rate $C$ (accounting for documented rounding/tolerance) $\rightarrow$ `contradictory`.
  - *Example*: Claim 99%; 50 compliant and 50 verified non-compliant ($n=100, y=50, u=0$). Upper bound is 50%, therefore contradictory.
- **Compatible with Unknowns**: If $u > 0$ and $C \le \text{Upper Bound}$, the claim cannot be contradicted from the available evidence $\rightarrow$ `insufficient_evidence` (or retained without contradiction; never described as proven compliance unless evidence supports that stronger claim).
  - *Example*: Claim 99%; 50 compliant and 50 unknown outcomes ($n=100, y=50, u=50$). Compatible interval $[50\%, 100\%]$; not contradictory.
- **Incomplete / Unknown Denominator**: If eligible population is unknown, the detector discloses the denominator gap and suspends full-population rate calculations.

### Evidence States
| State | Trigger Condition |
| :--- | :--- |
| `contradictory` | Claimed rate $C$ strictly exceeds the valid upper bound $(y + u) / n$. |
| `insufficient_evidence` | Declared claims source missing, incomplete denominator, or claimed rate falls inside uncertainty interval with unknown outcomes $u > 0$. |
| `supported` | Claimed rate $C$ is mathematically within verified bounds with 0 unknowns and evidence affirmatively supports compliance. |

---

## 5. Rule POL-REC-005: Post-Remediation Recurrence Context

- **Obligation ID**: `POL-REC-005`
- **Family**: Asset Incident Recurrence Context
- **Target Objects**: Assets with recurring alert conditions (`assets`, `alerts`, `cases`)
- **Policy Standard**: Identifies recurring alert patterns on assets following previous remediations.

### Evaluation Logic
- **Hypothesis Framing**: Findings are explicitly phrased as investigative hypotheses (e.g., *"Hypothesis: Asset X exhibited recurring alert conditions..."*). They never make causal accusations such as "failure to learn".
- **External Remediation Ownership**: If an approved exception or external vendor/maintenance owner is responsible for the recurring condition, the rule excuses the finding.
- **Peer Comparison Status**: In Task 2, count-deficit models are pending. Peer comparisons are explicitly labeled `peer_comparison_unavailable`.

### Evidence States
| State | Trigger Condition |
| :--- | :--- |
| `potential_concern` | Asset exceeds recurring alert threshold across multiple cases without external owner. |
| `not_applicable` | Recurring alert condition covered by approved maintenance exception or external owner. |
| `insufficient_evidence` | Alert linkage or case histories missing from submission. |

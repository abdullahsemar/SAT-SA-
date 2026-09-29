# Supervisory Review Portfolio & Examiner Decision Policy

## 1. Overview & Core Invariants

SAT-SA provides supervisory decision-support for human bank examiners assessing Cybersecurity Entity (CSE) submissions. In accordance with `docs/BUILD_RULES.md`:
1. **No Autonomous Supervisory Verdicts**: SAT-SA never issues autonomous pass/fail sanctions or closes supervisory findings automatically. Human examiners conduct deliberations and record determinations.
2. **Machine Finding Immutability**: Accepted submissions and analytical findings remain strictly immutable. Examiner determinations, overrides, and notes are persisted in separate audit tables (`review_decisions`, `evidence_requests`, `review_audit_events`).
3. **No Resampling Upon Reopening**: Saved review portfolios freeze the selected items, rank ordering, marginal reasons, and sampling metadata. Reopening a portfolio loads persisted database records without re-execution. New examiner requests create new revisions.
4. **Offline Local Records Only**: Evidence requests are stored as local audit records. SAT-SA never emails or dispatches network notifications to supervised entities.

---

## 2. Mathematical Selection Objective

The portfolio selection engine selects a limited set of review units $S$ from a candidate population to maximize coverage of supervisory hypotheses and group diversity under diminishing returns:

$$F(S) = \alpha \sum_{h \in H} w_h \min\left(1, \sum_{i \in S} \text{coverage}_{i, h}\right) + \beta \sum_{g \in G} w_g \min\left(1, |S \cap g|\right) + \gamma \sum_{i \in S} \text{review\_value}_i$$

### 2.1 Versioned Nonnegative Weights (`v1.0`)

| Parameter | Default Weight | Meaning & Rationale |
|---|---|---|
| $\alpha$ | `2.0` | **Hypothesis Diversity Term**: Rewards selecting items that cover distinct supervisory hypotheses. Diminishing returns apply: once hypothesis $h$ is fully covered ($\sum \ge 1.0$), marginal gain from additional duplicates drops to zero for this term. |
| $\beta$ | `1.0` | **Group Diversity Term**: Rewards spreading examiner attention across multiple dimensions (e.g. `asset`, `category`, `period`). Diminishing returns apply once at least one item from group $g$ is selected. |
| $\gamma$ | `0.5` | **Examiner Review Rubric Term**: Rewards intrinsic supervisory interest based on severity and evidence states. |

> [!IMPORTANT]
> **Rubric Notice**: Review values are a supervisory heuristic rubric (e.g. Critical = 3.0, High = 2.0, Medium = 1.0, Low = 0.5), **NOT** calibrated defect probabilities or SOC risk percentages.

### 2.2 Greedy Marginal Cost-Efficiency Heuristic

At each step, unselected feasible candidate $i$ is chosen to maximize marginal gain per estimated review minute:

$$\text{efficiency}(i \mid S) = \frac{F(S \cup \{i\}) - F(S)}{\text{estimated\_review\_minutes}_i}$$

- **Deterministic Tie-Breaking**: Broken deterministically on `(efficiency, review_value, unit_id)`.
- **Budgets**: `max_items` (integer $> 0$) and optional `max_minutes` (positive float). Non-positive budgets or costs are strictly rejected with HTTP 422.
- **Duplication Caps**: Configurable limits (default: max 3 per asset, max 4 per category) to prevent queue overconcentration.
- **Bounded Candidate Pool**: Preserves rare hypotheses by sorting on inverse hypothesis frequency; avoids $O(N^2)$ all-pairs similarity matrices.

---

## 3. Stratified Sampling & Reserve Capacity

To prevent confirmation bias and explore baseline operations, portfolios reserve separate capacities across three declared strata:

| Stratum | Default 20-Item Allocation | Purpose & Selection Method |
|---|---|---|
| **Targeted** | 14 items (70%) | Greedy marginal cost-efficiency optimization on flagged machine findings and identified anomalies. |
| **Control** | 4 items (20%) | Uniform random sampling with saved seed from declared **unflagged eligible population** (closed compliant cases, quiet healthy assets). Logged exclusions prevent overlap with machine findings. |
| **Exploratory**| 2 items (10%) | Boundary condition sampling (edge cases, secondary KPI claims) to discover unknown unknowns. |

### 3.1 Strict Shortfall Reporting Invariant
When declared eligible records are fewer than the requested stratum quota (or when minute budgets prevent filling capacity), **SAT-SA returns fewer items with an explicit shortfall record**. Under no circumstances does the system pad queues with duplicate entries or invent synthetic control records.

---

## 4. Formal Heuristic & Statistical Disclaimers

> [!WARNING]
> **No Cardinality-Constrained Greedy Guarantee**:
> Standard submodular $(1 - 1/e)$ approximation guarantees apply strictly to cardinality-constrained maximization. They do **not** apply to this knapsack cost-budget, stratified-quota, and duplication-capped heuristic.

> [!WARNING]
> **No Population Prevalence Estimation**:
> The review queue is targeted and diversity-optimized. It **cannot** be used to estimate true population prevalence of SOC defects or non-compliance. Any statistical prevalence audit requires a separately justified probability sampling design with declared, non-zero inclusion probabilities.

---

## 5. Decision Lineage & Optimistic Concurrency

Examiners record determinations through dedicated API endpoints:

### 5.1 Decision States
- **Finding Determinations**: `substantiated`, `not_substantiated`, `additional_evidence_required`, `not_applicable`.
- **Item Review Determinations** (Controls & Exploratory): `reviewed_no_concern`, `concern_observed`, `additional_evidence_required`.

### 5.2 Concurrency & Citation Scope Invariants
- **Append-Only Lineage**: Corrections do not overwrite previous records; they append a new decision with an incremented version number referencing `superseded_decision_id`.
- **Optimistic Concurrency (HTTP 409)**: If an examiner attempts to supersede a decision that has already been superseded by another reviewer, the API rejects the update with `409 CONFLICT`.
- **Scope-Checked Evidence IDs (HTTP 400)**: Any cited evidence ID must exist within the target entity's submitted evidence records. Unverified or cross-entity IDs are rejected with `400 BAD REQUEST`.

---

## 6. Local Evidence Requests

When missing artifacts or competing explanations prevent determination, examiners file local evidence requests specifying:
1. `missing_artifact`: Precise description of missing evidentiary artifacts.
2. `distinguishing_question`: The concrete supervisory question that resolves competing explanations (e.g. distinguishing authorized cron from remote code execution). Generic requests like "send more data" are prohibited.
3. `responsible_owner` & `due_date`: Designated entity contact role and UTC deadline.
4. All requests remain local database records within loopback isolation.

# SAT-SA Build Rules & Architectural Invariants

These architectural invariants are mandatory for SAT-SA (Supervisory Analytics Tool for SOC Assessment). All tasks and implementations must strictly adhere to these rules. Subsequent tasks must read and comply with this file.

## 1. Offline Runtime
- All components must run entirely offline on loopback (`127.0.0.1` / `localhost`).
- No outbound network connections, phone-homes, external CDNs, Google Fonts, remote scripts, or telemetry services are permitted.
- Static assets must be bundled locally.

## 2. No External APIs / No Remote Model Code
- No cloud AI services, external LLM endpoints, or remote inference APIs.
- Any automated analysis or NLP added in future tasks must execute strictly in-process or via vetted, local offline runtimes without downloading weights on the fly.
- Unsafe serialized models (e.g., untrusted pickle files) or execution of arbitrary code/macros from submitted files is strictly prohibited.

## 3. No Autonomous Supervisory Verdicts
- SAT-SA is an evidence-intake and decision-support analytical workbench for human examiners.
- The tool must never issue autonomous supervisory pass/fail sanctions or replace human regulatory judgment.
- Automated checks produce transparent evidence-quality indicators, discrepancy flags, and coverage metrics.

## 4. Immutable Accepted Submissions & Completed Analyses
- Once a submission revision is committed/accepted, it is cryptographically locked and immutable.
- Neither raw evidence files, extracted raw records, nor normalized records may be edited in place.
- Re-submissions or updates must be represented as new revisions or separate submissions with distinct lineage.

## 5. Source References for Every Observation
- Every validation issue, quality metric, normalized record, and downstream finding must carry precise provenance:
  - Source system identifier
  - File locator (line/row number or JSON pointer)
  - Raw record ID and server-computed SHA-256 hash
- An examiner must always be able to trace an observation back to the exact submitted raw record bytes.

## 6. No Treating Missing Data as Failed Operations
- Missing data must not be conflated with operational failure or security non-compliance.
- Missing optional sources, uninstrumented fields, or missing coverage observations must be classified explicitly as `UNKNOWN` or `NOT_APPLICABLE`.
- Incomplete exports must be distinguished from operational lapses in the supervised entity.

## 7. Unknown and Not-Applicable are First-Class Values
- Typed schemas must retain explicit representations for unknown (`"UNKNOWN"`, `None`) or not-applicable states.
- Under no circumstances should missing or unknown numerical values be silently coerced to `0`, empty strings, or arbitrary defaults.

## 8. Conditional Policy Obligations
- Supervisory criteria and validation checks depend on context (e.g., entity size, declared scope, tier).
- Rules must evaluate applicability conditions before raising compliance or quality issues.

## 9. Human Decisions Stored Separately
- Examiner notes, overrides, determinations, and review decisions must be stored in independent audit tables distinct from the ingested evidence records.
- Ingested evidence remains untainted by supervisory deliberations.

## 10. API-Backed UI Values
- The user interface must never mock, hardcode, or simulate backend state or operational metrics.
- All metrics, statuses, quality counts, and record inspections must originate from authenticated API endpoints.

## 11. No Real Sensitive Data in Fixtures
- All test fixtures, scenarios, and development seeds must be 100% synthetic.
- No production entity names, actual IP addresses, real employee credentials, or proprietary SOC telemetry may be committed to this repository.

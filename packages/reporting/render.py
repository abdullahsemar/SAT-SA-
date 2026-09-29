"""HTML renderer for self-contained printable assessment reports.

Preserves core architectural invariants:
- Zero external CDNs, fonts, or remote scripts; 100% offline self-contained HTML.
- Strict HTML escaping on all dynamic fields, narratives, and examiner rationales.
- Never combines machine hypotheses and examiner conclusions into an unlabeled final verdict.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict


def esc(val: Any) -> str:
    """Strictly escapes an arbitrary value into safe HTML text."""
    if val is None:
        return ""
    return html.escape(str(val))


class HTMLReportRenderer:
    """Renders a self-contained HTML document from a report snapshot and manifest."""

    def __init__(self, template_path: Path | None = None):
        if template_path and template_path.is_file():
            with open(template_path, "r", encoding="utf-8") as f:
                self.template_content = f.read()
        else:
            default_path = Path(__file__).parent / "templates" / "assessment.html"
            if default_path.is_file():
                with open(default_path, "r", encoding="utf-8") as f:
                    self.template_content = f.read()
            else:
                raise FileNotFoundError(f"Template file not found at {default_path}")

    def render(self, snapshot: Dict[str, Any], manifest: Dict[str, Any]) -> str:
        """Renders complete standalone HTML from snapshot and checksum manifest."""
        entity = snapshot.get("entity", {})
        sub = snapshot.get("submission", {})
        run = snapshot.get("analysis_run", {})
        methodology = snapshot.get("methodology", {})
        findings = snapshot.get("findings", [])
        portfolio = snapshot.get("review_portfolio") or {}
        decisions = snapshot.get("examiner_decisions", {})
        ev_requests = snapshot.get("evidence_requests", [])
        prior_runs = snapshot.get("comparable_prior_runs", [])
        semantic = methodology.get("semantic_model", {})

        # 1. Submission files rows
        files_rows = []
        for sf in sub.get("files", []):
            fname = sf.get("original_filename") or sf.get("filename", "")
            ftype = sf.get("record_type") or sf.get("file_type", "")
            fsize = sf.get("byte_size", sf.get("size_bytes", 0))
            decl = sf.get("declared_row_count")
            act = sf.get("actual_row_count", sf.get("record_count", 0))
            if decl is not None:
                count_str = f"{act:,} (declared: {decl:,})"
            else:
                count_str = f"{act:,}"
            source_id = sf.get("source_id", "")
            if source_id:
                name_html = (
                    f"<strong>{esc(fname)}</strong> "
                    f"<span style='color: var(--text-muted); font-size: 11px;'>({esc(source_id)})</span>"
                )
            else:
                name_html = f"<strong>{esc(fname)}</strong>"

            files_rows.append(
                f"<tr>"
                f"<td>{name_html}</td>"
                f"<td><code>{esc(ftype)}</code></td>"
                f"<td>{fsize:,}</td>"
                f"<td>{esc(count_str)}</td>"
                f"<td><code>{esc(sf.get('sha256_hash', ''))}</code></td>"
                f"</tr>"
            )
        submission_files_html = (
            "\n".join(files_rows)
            if files_rows
            else "<tr><td colspan='5'>No files recorded.</td></tr>"
        )

        # 2. Findings cards
        findings_cards = []
        for f in findings:
            sev = esc(f.get("severity", "medium")).lower()
            sev_class = f"badge-{sev}"
            sup_records = f.get("supporting_records", [])
            contra_records = f.get("contradicting_records", [])
            alts = f.get("alternatives", [])
            unknowns = f.get("unknowns", [])
            sim_passages = f.get("similar_passages", [])

            sup_html = ""
            if sup_records:
                sup_items = "".join(
                    f"<li><code>{esc(r.get('raw_record_id') or r)}</code></li>"
                    for r in sup_records[:5]
                )
                sup_html = f"<div class='item-subheading'>Supporting Records ({len(sup_records)})</div><ul>{sup_items}</ul>"

            contra_html = ""
            if contra_records:
                contra_items = "".join(
                    f"<li><code>{esc(r.get('raw_record_id') or r)}</code></li>"
                    for r in contra_records[:5]
                )
                contra_html = f"<div class='item-subheading'>Contradicting / Mitigating Records ({len(contra_records)})</div><ul>{contra_items}</ul>"

            alts_html = ""
            if alts:
                alt_items = "".join(f"<li>{esc(a)}</li>" for a in alts)
                alts_html = f"<div class='item-subheading'>Operational Alternatives</div><ul>{alt_items}</ul>"

            unknowns_html = ""
            if unknowns:
                unk_items = "".join(f"<li>{esc(u)}</li>" for u in unknowns)
                unknowns_html = (
                    f"<div class='item-subheading'>Declared Unknowns</div><ul>{unk_items}</ul>"
                )

            sim_html = ""
            if sim_passages:
                sim_items = "".join(
                    f"<li>Score: {p.get('score', 0):.2f} - {esc(p.get('preview'))}</li>"
                    for p in sim_passages[:3]
                )
                sim_html = f"<div class='item-subheading'>Semantic Similar Investigation Passages</div><ul>{sim_items}</ul>"

            findings_cards.append(
                f"<div class='item-card'>"
                f"<div class='item-header'>"
                f"<div class='item-title'><strong>{esc(f.get('rule_id'))}</strong>: {esc(f.get('rule_title'))}</div>"
                f"<div><span class='badge {sev_class}'>{esc(f.get('severity'))}</span> "
                f"<span class='badge badge-not-applicable'>{esc(f.get('rule_category'))}</span></div>"
                f"</div>"
                f"<div class='item-body'>"
                f"<p><strong>Observation:</strong> {esc(f.get('observation'))}</p>"
                f"<p><strong>Supervisory Context:</strong> {esc(f.get('supervisory_significance'))}</p>"
                f"{sup_html}"
                f"{contra_html}"
                f"{alts_html}"
                f"{unknowns_html}"
                f"{sim_html}"
                f"</div>"
                f"</div>"
            )
        findings_cards_html = (
            "\n".join(findings_cards)
            if findings_cards
            else "<p>No automated findings detected for this submission.</p>"
        )

        # 3. Portfolio Summary Block & Items Rows
        if portfolio:
            p_summary = portfolio.get("summary", {})
            p_summary_html = (
                f"<div class='grid-2'>"
                f"<div class='data-card'>"
                f"<h3>Optimization Strata Allocation</h3>"
                f"<p><strong>Total Items:</strong> {p_summary.get('selected_count', 0)} / {p_summary.get('budget_items', 0)}</p>"
                f"<p><strong>Targeted:</strong> {p_summary.get('strata_counts', {}).get('targeted', 0)} | "
                f"<strong>Control:</strong> {p_summary.get('strata_counts', {}).get('control', 0)} | "
                f"<strong>Exploratory:</strong> {p_summary.get('strata_counts', {}).get('exploratory', 0)}</p>"
                f"<p><strong>Shortfalls:</strong> {esc(p_summary.get('shortfalls', {}))}</p>"
                f"</div>"
                f"<div class='data-card'>"
                f"<h3>Diminishing-Returns Coverage</h3>"
                f"<p><strong>Hypotheses Covered:</strong> {p_summary.get('distinct_hypotheses_covered_count', 0)}</p>"
                f"<p><strong>Review Time Budget:</strong> {p_summary.get('total_review_minutes', 0):.1f} min / {p_summary.get('budget_minutes', 0)} min</p>"
                f"<p><strong>Objective Value:</strong> {p_summary.get('total_objective_score', 0):.2f}</p>"
                f"</div>"
                f"</div>"
            )
            item_rows = []
            for item in portfolio.get("items", []):
                stratum = esc(item.get("stratum", "targeted")).lower()
                badge_class = f"badge-{stratum}"
                unk_text = ", ".join(esc(u) for u in item.get("unknowns", [])) or "None declared"
                learn_text = esc(item.get("what_examiner_could_learn", ""))
                item_rows.append(
                    f"<tr>"
                    f"<td><strong>#{item.get('rank')}</strong></td>"
                    f"<td><span class='badge {badge_class}'>{esc(item.get('stratum'))}</span></td>"
                    f"<td><code>{esc(item.get('unit_id'))}</code></td>"
                    f"<td>{esc(item.get('unit_type'))}</td>"
                    f"<td>{item.get('review_minutes', 0):.1f}</td>"
                    f"<td>{item.get('review_value', 0):.2f}</td>"
                    f"<td><p>{learn_text}</p><p style='color: var(--text-muted); font-size: 11px;'><strong>Unknowns:</strong> {unk_text}</p></td>"
                    f"</tr>"
                )
            portfolio_items_html = (
                "\n".join(item_rows)
                if item_rows
                else "<tr><td colspan='7'>No items in portfolio.</td></tr>"
            )
            portfolio_revision = str(portfolio.get("revision", 1))
        else:
            p_summary_html = "<div class='data-card'><p>No review portfolio was attached to this assessment run.</p></div>"
            portfolio_items_html = "<tr><td colspan='7'>No portfolio items.</td></tr>"
            portfolio_revision = "N/A"

        # 4. Finding & Item Decisions Rows
        f_decisions = decisions.get("finding_decisions", [])
        f_rows = []
        for fd in f_decisions:
            st = esc(fd.get("state", "")).lower()
            badge_class = (
                "badge-substantiated"
                if st == "substantiated"
                else ("badge-no-concern" if st == "not_substantiated" else "badge-evidence")
            )
            cited_text = (
                ", ".join(f"<code>{esc(c)}</code>" for c in fd.get("cited_evidence_ids", []))
                or "None cited"
            )
            f_rows.append(
                f"<tr>"
                f"<td><code>{esc(fd.get('finding_id'))}</code></td>"
                f"<td><span class='badge {badge_class}'>{esc(fd.get('state'))}</span></td>"
                f"<td>{esc(fd.get('rationale'))}</td>"
                f"<td>{cited_text}</td>"
                f"<td><code>{esc(fd.get('reviewer_id'))}</code></td>"
                f"<td>{esc(fd.get('created_at'))}</td>"
                f"</tr>"
            )
        finding_decisions_html = (
            "\n".join(f_rows)
            if f_rows
            else "<tr><td colspan='6'>No finding determinations recorded before cutoff.</td></tr>"
        )

        i_decisions = decisions.get("item_decisions", [])
        i_rows = []
        for id_item in i_decisions:
            st = esc(id_item.get("state", "")).lower()
            badge_class = (
                "badge-no-concern"
                if st == "reviewed_no_concern"
                else ("badge-substantiated" if st == "concern_observed" else "badge-evidence")
            )
            cited_text = (
                ", ".join(f"<code>{esc(c)}</code>" for c in id_item.get("cited_evidence_ids", []))
                or "None cited"
            )
            i_rows.append(
                f"<tr>"
                f"<td><code>{esc(id_item.get('review_item_id'))}</code></td>"
                f"<td><span class='badge {badge_class}'>{esc(id_item.get('state'))}</span></td>"
                f"<td>{esc(id_item.get('rationale'))}</td>"
                f"<td>{cited_text}</td>"
                f"<td><code>{esc(id_item.get('reviewer_id'))}</code></td>"
                f"<td>{esc(id_item.get('created_at'))}</td>"
                f"</tr>"
            )
        item_decisions_html = (
            "\n".join(i_rows)
            if i_rows
            else "<tr><td colspan='6'>No item-level reviews recorded before cutoff.</td></tr>"
        )

        # 5. Evidence requests rows
        ev_rows = []
        for ev in ev_requests:
            target = (
                f"Finding: {esc(ev.get('finding_id'))}"
                if ev.get("finding_id")
                else f"Item: {esc(ev.get('review_item_id'))}"
            )
            ev_rows.append(
                f"<tr>"
                f"<td><code>{esc(ev.get('request_id')[:8])}</code></td>"
                f"<td>{target}</td>"
                f"<td><p><strong>{esc(ev.get('missing_artifact'))}</strong></p><p style='font-size: 11px; color: var(--text-muted);'>{esc(ev.get('distinguishing_question'))}</p></td>"
                f"<td>{esc(ev.get('responsible_owner'))}</td>"
                f"<td>{esc(ev.get('due_date') or 'N/A')}</td>"
                f"<td><span class='badge badge-evidence'>{esc(ev.get('status'))}</span></td>"
                f"</tr>"
            )
        evidence_requests_html = (
            "\n".join(ev_rows)
            if ev_rows
            else "<tr><td colspan='6'>No pending evidence requests.</td></tr>"
        )

        # 6. Prior runs block
        if prior_runs:
            pr_rows = []
            for pr in prior_runs:
                pr_rows.append(
                    f"<tr>"
                    f"<td><code>{esc(pr.get('run_id'))}</code></td>"
                    f"<td>{esc(pr.get('period_cutoff'))}</td>"
                    f"<td>{pr.get('findings_count', 0)}</td>"
                    f"<td><code>{esc(pr.get('summary_counts'))}</code></td>"
                    f"</tr>"
                )
            prior_runs_block = (
                f"<table>"
                f"<thead><tr><th>Prior Run ID</th><th>Period Cutoff</th><th>Findings Count</th><th>Summary Metrics</th></tr></thead>"
                f"<tbody>{''.join(pr_rows)}</tbody>"
                f"</table>"
            )
        else:
            prior_runs_block = (
                "<div class='data-card'>"
                "<p><strong>No comparable prior data.</strong> This is the initial assessment submission for this entity, or prior runs are outside the declared supervisory comparability scope. No synthetic historical trend has been fabricated.</p>"
                "</div>"
            )

        # 7. Checksum Manifest Preview
        manifest_preview = esc(json.dumps(manifest, indent=2))

        # Perform replacement in template
        rendered = self.template_content
        replacements = {
            "{{ entity_id }}": esc(entity.get("entity_id")),
            "{{ period_start }}": esc(sub.get("period_start")),
            "{{ period_end }}": esc(sub.get("period_end")),
            "{{ run_id }}": esc(run.get("run_id")),
            "{{ decision_cutoff_time }}": esc(snapshot.get("decision_cutoff_time")),
            "{{ supervisory_notice }}": esc(methodology.get("supervisory_notice")),
            "{{ revision }}": esc(sub.get("revision")),
            "{{ submission_id }}": esc(sub.get("submission_id")),
            "{{ submission_status }}": esc(sub.get("status")),
            "{{ source_timezone }}": esc(entity.get("source_timezone")),
            "{{ validation_issues_count }}": str(sub.get("validation_issues_count", 0)),
            "{{ policy_version }}": esc(run.get("policy_version")),
            "{{ rule_version }}": esc(run.get("rule_version")),
            "{{ seed }}": str(run.get("seed")),
            "{{ completed_at }}": esc(run.get("completed_at") or "In Progress"),
            "{{ submission_files_rows }}": submission_files_html,
            "{{ findings_count }}": str(len(findings)),
            "{{ findings_cards }}": findings_cards_html,
            "{{ portfolio_revision }}": portfolio_revision,
            "{{ portfolio_summary_block }}": p_summary_html,
            "{{ portfolio_items_rows }}": portfolio_items_html,
            "{{ total_decisions_count }}": str(decisions.get("total_decisions_count", 0)),
            "{{ finding_decisions_rows }}": finding_decisions_html,
            "{{ item_decisions_rows }}": item_decisions_html,
            "{{ evidence_requests_count }}": str(len(ev_requests)),
            "{{ evidence_requests_rows }}": evidence_requests_html,
            "{{ trend_status }}": esc(snapshot.get("trend_status")),
            "{{ prior_runs_block }}": prior_runs_block,
            "{{ report_schema_version }}": esc(snapshot.get("report_schema_version")),
            "{{ semantic_mode }}": esc(semantic.get("mode")),
            "{{ semantic_model_name }}": esc(
                semantic.get("model_name") or "None (Lexical Fallback)"
            ),
            "{{ semantic_manifest_hash }}": esc(semantic.get("manifest_sha256") or "None"),
            "{{ semantic_commit }}": esc(semantic.get("commit") or "None"),
            "{{ input_hash }}": esc(run.get("input_hash")),
            "{{ snapshot_generated_at }}": esc(snapshot.get("snapshot_generated_at")),
            "{{ checksum_manifest_preview }}": manifest_preview,
        }

        for key, val in replacements.items():
            rendered = rendered.replace(key, val)

        return rendered

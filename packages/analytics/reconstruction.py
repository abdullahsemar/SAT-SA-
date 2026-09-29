import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from packages.analytics.context import AssessmentContext


@dataclass
class ChainNode:
    id: str
    record_type: str
    native_id: str
    label: str
    timestamp: str | None
    details: dict[str, Any]


@dataclass
class ChainEdge:
    source_id: str
    target_id: str
    link_type: str
    is_uncertain: bool = False
    confidence: float = 1.0


@dataclass
class ReconstructedChain:
    root_id: str
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    omissions: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)


class EvidenceGraphReconstructor:
    def __init__(self, ctx: AssessmentContext):
        self.ctx = ctx
        self._build_indexes()

    def _build_indexes(self):
        # Index links
        # case_id -> list of alert_id
        # alert_id -> list of case_id
        self.case_to_alerts: dict[str, list[str]] = {}
        self.alert_to_cases: dict[str, list[str]] = {}

        for link in self.ctx.records_by_type.get("case_alert_links", []):
            if link.is_quarantined:
                continue
            data = json.loads(link.normalized_data)
            c_id = data.get("case_id")
            a_id = data.get("alert_id")
            if c_id and a_id:
                self.case_to_alerts.setdefault(c_id, []).append(a_id)
                self.alert_to_cases.setdefault(a_id, []).append(c_id)

        self.case_actions: dict[str, list[Any]] = {}
        for act in self.ctx.records_by_type.get(
            "investigation_actions", []
        ) + self.ctx.records_by_type.get("actions", []):
            if not act.is_quarantined:
                d = (
                    json.loads(act.normalized_data)
                    if isinstance(act.normalized_data, str)
                    else dict(act.normalized_data)
                )
                nid = str(act.native_id)
                d.setdefault("native_id", nid)
                d.setdefault("action_id", nid)
                d["_record_id"] = str(act.id)
                d["_source_ref"] = self.ctx.get_source_ref(act)
                if d.get("case_id"):
                    self.case_actions.setdefault(str(d["case_id"]), []).append(d)

        self.case_escalations: dict[str, list[Any]] = {}
        for esc in self.ctx.records_by_type.get("escalations", []):
            if not esc.is_quarantined:
                d = (
                    json.loads(esc.normalized_data)
                    if isinstance(esc.normalized_data, str)
                    else dict(esc.normalized_data)
                )
                nid = str(esc.native_id)
                d.setdefault("native_id", nid)
                d.setdefault("escalation_id", nid)
                d["_record_id"] = str(esc.id)
                d["_source_ref"] = self.ctx.get_source_ref(esc)
                if d.get("case_id"):
                    self.case_escalations.setdefault(str(d["case_id"]), []).append(d)

        self.case_remediations: dict[str, list[Any]] = {}
        for rem in self.ctx.records_by_type.get("remediations_validations", []):
            if not rem.is_quarantined:
                d = (
                    json.loads(rem.normalized_data)
                    if isinstance(rem.normalized_data, str)
                    else dict(rem.normalized_data)
                )
                nid = str(rem.native_id)
                d.setdefault("native_id", nid)
                d.setdefault("remediation_id", nid)
                d["_record_id"] = str(rem.id)
                d["_source_ref"] = self.ctx.get_source_ref(rem)
                if d.get("case_id"):
                    self.case_remediations.setdefault(str(d["case_id"]), []).append(d)

        self.asset_alerts: dict[str, list[dict[str, Any]]] = {}
        self.alerts_by_id: dict[str, dict[str, Any]] = {}

        # Index exceptions by affected_scope
        self.scope_exceptions: dict[str, list[Any]] = {}
        for exc in self.ctx.records_by_type.get("exceptions", []):
            if not exc.is_quarantined:
                d = json.loads(exc.normalized_data)
                sc = d.get("affected_scope")
                if sc:
                    self.scope_exceptions.setdefault(sc, []).append(exc)

        # Index alerts from normalized DB records
        for alt in self.ctx.records_by_type.get("alerts", []):
            if not alt.is_quarantined:
                d = (
                    json.loads(alt.normalized_data)
                    if isinstance(alt.normalized_data, str)
                    else dict(alt.normalized_data)
                )
                nid = str(alt.native_id)
                d.setdefault("native_id", nid)
                d.setdefault("alert_id", nid)
                d["_record_id"] = str(alt.id)
                d["_source_ref"] = self.ctx.get_source_ref(alt)
                self.alerts_by_id[nid] = d
                self.alerts_by_id[str(alt.id)] = d
                ast_id = d.get("asset_id") or d.get("affected_asset_id")
                if ast_id and str(ast_id) != "UNKNOWN":
                    self.asset_alerts.setdefault(str(ast_id), []).append(d)

        # Also populate from get_records for scenario reports / direct dicts
        for link in self.ctx.get_records("case_alert_links"):
            c_id = link.get("case_id")
            a_id = link.get("alert_id")
            if c_id and a_id:
                self.case_to_alerts.setdefault(c_id, []).append(a_id)
                self.alert_to_cases.setdefault(a_id, []).append(c_id)

        for act in self.ctx.get_records("actions") + self.ctx.get_records("investigation_actions"):
            c_id = act.get("case_id")
            if c_id:
                if act not in self.case_actions.get(c_id, []):
                    self.case_actions.setdefault(c_id, []).append(act)

        for alt in self.ctx.get_records("alerts"):
            a_id = str(alt.get("alert_id") or alt.get("id") or alt.get("native_id") or "")
            if a_id:
                d = dict(alt)
                d.setdefault("native_id", a_id)
                d.setdefault("alert_id", a_id)
                rec_id = str(d.get("id") or a_id)
                d.setdefault("_record_id", rec_id)
                if a_id not in self.alerts_by_id:
                    self.alerts_by_id[a_id] = d
                if rec_id not in self.alerts_by_id:
                    self.alerts_by_id[rec_id] = d
                ast_id = d.get("asset_id") or d.get("affected_asset_id")
                if ast_id and str(ast_id) != "UNKNOWN":
                    existing = self.asset_alerts.get(str(ast_id), [])
                    if not any(
                        x.get("native_id") == a_id or x.get("_record_id") == rec_id
                        for x in existing
                    ):
                        self.asset_alerts.setdefault(str(ast_id), []).append(d)

        # Aliases
        self.case_alerts = self.case_to_alerts
        self.alert_cases = self.alert_to_cases

    @staticmethod
    def _parse_dt(val: Any):
        import datetime

        if not val:
            return None
        if isinstance(val, datetime.datetime):
            return val if val.tzinfo else val.replace(tzinfo=datetime.timezone.utc)
        try:
            dt = datetime.datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)
        except Exception:
            return None

    def reconstruct_case_chain(self, case_native_id: str) -> ReconstructedChain:
        chain = ReconstructedChain(root_id=case_native_id)
        case_rec = self.ctx.records_by_native_id.get(("cases", case_native_id))

        case_data = None
        case_rec_id = case_native_id
        if case_rec:
            case_data = json.loads(case_rec.normalized_data)
            case_rec_id = case_rec.id
        else:
            for c in self.ctx.get_records("cases"):
                if (
                    c.get("native_id") == case_native_id
                    or c.get("case_id") == case_native_id
                    or c.get("id") == case_native_id
                ):
                    case_data = c
                    case_rec_id = c.get("id") or case_native_id
                    break

        if not case_data:
            chain.omissions.append(f"Case '{case_native_id}' not found in ingested cases.")
            return chain

        chain.nodes.append(
            ChainNode(
                id=case_rec_id,
                record_type="cases",
                native_id=case_native_id,
                label=f"Case {case_native_id} ({case_data.get('severity', 'UNKNOWN')})",
                timestamp=case_data.get("created_at"),
                details=case_data,
            ).__dict__
        )

        if case_data.get("created_at"):
            chain.timeline.append(
                {
                    "event": f"Case Created: {case_native_id}",
                    "timestamp": case_data["created_at"],
                    "record_type": "cases",
                    "record_id": case_rec_id,
                }
            )

        # 1. Linked Alerts
        linked_alert_ids = self.case_to_alerts.get(case_native_id, [])
        if not linked_alert_ids:
            chain.uncertainties.append(
                f"No alerts linked to case {case_native_id} via case_alert_links."
            )

        for a_id in linked_alert_ids:
            alt_rec = self.ctx.records_by_native_id.get(("alerts", a_id))
            alt_data = None
            alt_id_val = a_id
            if alt_rec:
                alt_data = json.loads(alt_rec.normalized_data)
                alt_id_val = alt_rec.id
            elif a_id in self.alerts_by_id:
                alt_data = self.alerts_by_id[a_id]
                alt_id_val = alt_data.get("alert_id") or a_id

            if alt_data:
                chain.nodes.append(
                    ChainNode(
                        id=alt_id_val,
                        record_type="alerts",
                        native_id=a_id,
                        label=f"Alert {a_id}: {alt_data.get('title', 'Untitled')}",
                        timestamp=alt_data.get("timestamp") or alt_data.get("created_at"),
                        details=alt_data,
                    ).__dict__
                )
                chain.edges.append(
                    ChainEdge(
                        source_id=alt_id_val,
                        target_id=case_rec_id,
                        link_type="triaged_into",
                        confidence=1.0,
                    ).__dict__
                )
                alert_ts = alt_data.get("timestamp") or alt_data.get("created_at")
                if alert_ts:
                    chain.timeline.append(
                        {
                            "event": f"Alert Triggered: {a_id}",
                            "timestamp": alert_ts,
                            "record_type": "alerts",
                            "record_id": alt_id_val,
                        }
                    )

                # Connected Asset
                ast_id = alt_data.get("affected_asset_id") or alt_data.get("asset_id")
                if ast_id and ast_id != "UNKNOWN":
                    ast_rec = self.ctx.records_by_native_id.get(("assets", ast_id))
                    ast_data = (
                        json.loads(ast_rec.normalized_data)
                        if ast_rec
                        else next(
                            (
                                a
                                for a in self.ctx.get_records("assets")
                                if (
                                    a.get("native_id") == ast_id
                                    or a.get("asset_id") == ast_id
                                    or a.get("id") == ast_id
                                )
                            ),
                            None,
                        )
                    )
                    if ast_data:
                        ast_node_id = ast_rec.id if ast_rec else ast_id
                        if not any(n["id"] == ast_node_id for n in chain.nodes):
                            chain.nodes.append(
                                ChainNode(
                                    id=ast_node_id,
                                    record_type="assets",
                                    native_id=ast_id,
                                    label=f"Asset {ast_id} ({ast_data.get('hostname', 'host')})",
                                    timestamp=ast_data.get("timestamp")
                                    or ast_data.get("created_at"),
                                    details=ast_data,
                                ).__dict__
                            )
                        chain.edges.append(
                            ChainEdge(
                                source_id=ast_node_id,
                                target_id=alt_id_val,
                                link_type="affected_by",
                            ).__dict__
                        )
            else:
                chain.omissions.append(
                    f"Linked alert '{a_id}' declared in links but record missing from alerts source."
                )

        # 2. Investigation Actions
        actions = self.case_actions.get(case_native_id, [])
        for act in actions:
            act_data = json.loads(act.normalized_data) if hasattr(act, "normalized_data") else act
            act_id = (
                getattr(act, "id", None)
                or act_data.get("action_id")
                or act_data.get("id")
                or str(uuid.uuid4())
            )
            act_native_id = getattr(act, "native_id", None) or act_data.get("action_id", act_id)
            act_type = act_data.get("action_type", "ACTION")
            act_ts = act_data.get("timestamp") or act_data.get("created_at")
            chain.nodes.append(
                ChainNode(
                    id=act_id,
                    record_type="investigation_actions",
                    native_id=act_native_id,
                    label=f"Action: {act_type}",
                    timestamp=act_ts,
                    details=act_data,
                ).__dict__
            )
            chain.edges.append(
                ChainEdge(
                    source_id=case_rec_id,
                    target_id=act_id,
                    link_type="performed_action",
                ).__dict__
            )
            if act_ts:
                chain.timeline.append(
                    {
                        "event": f"Action Performed: {act_type}",
                        "timestamp": act_ts,
                        "record_type": "investigation_actions",
                        "record_id": act_id,
                    }
                )

        # 3. Escalations
        escalations = self.case_escalations.get(case_native_id, [])
        for esc in escalations:
            esc_data = json.loads(esc.normalized_data) if hasattr(esc, "normalized_data") else esc
            esc_id = (
                getattr(esc, "id", None)
                or esc_data.get("action_id")
                or esc_data.get("id")
                or str(uuid.uuid4())
            )
            esc_native_id = getattr(esc, "native_id", None) or esc_data.get("action_id", esc_id)
            esc_level = esc_data.get("escalation_level") or esc_data.get(
                "action_type", "ESCALATION"
            )
            esc_ts = esc_data.get("timestamp") or esc_data.get("created_at")
            chain.nodes.append(
                ChainNode(
                    id=esc_id,
                    record_type="escalations",
                    native_id=esc_native_id,
                    label=f"Escalation: {esc_level}",
                    timestamp=esc_ts,
                    details=esc_data,
                ).__dict__
            )
            chain.edges.append(
                ChainEdge(
                    source_id=case_rec_id,
                    target_id=esc_id,
                    link_type="escalated_to",
                ).__dict__
            )
            if esc_ts:
                chain.timeline.append(
                    {
                        "event": f"Escalated ({esc_level} -> {esc_data.get('notified_party', 'Team')})",
                        "timestamp": esc_ts,
                        "record_type": "escalations",
                        "record_id": esc_id,
                    }
                )

        # 4. Remediations
        remediations = self.case_remediations.get(case_native_id, [])
        for rem in remediations:
            rem_data = json.loads(rem.normalized_data) if hasattr(rem, "normalized_data") else rem
            rem_id = (
                getattr(rem, "id", None)
                or rem_data.get("remediation_id")
                or rem_data.get("id")
                or str(uuid.uuid4())
            )
            rem_native_id = getattr(rem, "native_id", None) or rem_data.get(
                "remediation_id", rem_id
            )
            rem_res = rem_data.get("result", "VERIFIED")
            rem_ts = rem_data.get("validation_date") or rem_data.get("created_at")
            chain.nodes.append(
                ChainNode(
                    id=rem_id,
                    record_type="remediations_validations",
                    native_id=rem_native_id,
                    label=f"Remediation: {rem_res}",
                    timestamp=rem_ts,
                    details=rem_data,
                ).__dict__
            )
            chain.edges.append(
                ChainEdge(
                    source_id=case_rec_id,
                    target_id=rem_id,
                    link_type="remediated_by",
                ).__dict__
            )
            if rem_ts:
                chain.timeline.append(
                    {
                        "event": f"Remediation Verified: {rem_data.get('action_summary', rem_res)}",
                        "timestamp": rem_ts,
                        "record_type": "remediations_validations",
                        "record_id": rem_id,
                    }
                )

        # Filter edges to valid nodes and deduplicate edges
        node_ids = {n["id"] for n in chain.nodes}
        seen_edges = set()
        valid_edges = []
        for e in chain.edges:
            if e["source_id"] in node_ids and e["target_id"] in node_ids:
                edge_key = (e["source_id"], e["target_id"], e.get("link_type"))
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    valid_edges.append(e)
        chain.edges = valid_edges

        # Sort timeline chronologically
        chain.timeline.sort(key=lambda x: x["timestamp"] or "")
        return chain

    def reconstruct_asset_chain(self, asset_native_id: str) -> ReconstructedChain:
        chain = ReconstructedChain(root_id=str(asset_native_id))
        ast_rec = self.ctx.records_by_native_id.get(("assets", str(asset_native_id)))

        ast_data = None
        ast_node_id = str(asset_native_id)
        if ast_rec:
            ast_data = (
                json.loads(ast_rec.normalized_data)
                if isinstance(ast_rec.normalized_data, str)
                else dict(ast_rec.normalized_data)
            )
            ast_node_id = str(ast_rec.id)
        else:
            for a in self.ctx.get_records("assets"):
                if (
                    str(a.get("native_id")) == str(asset_native_id)
                    or str(a.get("asset_id")) == str(asset_native_id)
                    or str(a.get("id")) == str(asset_native_id)
                ):
                    ast_data = dict(a)
                    ast_node_id = str(a.get("id") or asset_native_id)
                    break

        if not ast_data:
            chain.omissions.append(f"Asset '{asset_native_id}' not found in inventory.")
            return chain

        chain.nodes.append(
            ChainNode(
                id=ast_node_id,
                record_type="assets",
                native_id=str(asset_native_id),
                label=f"Asset {asset_native_id}: {ast_data.get('hostname', 'host')}",
                timestamp=ast_data.get("timestamp") or ast_data.get("created_at"),
                details=ast_data,
            ).__dict__
        )

        # Linked alerts
        alerts = self.asset_alerts.get(str(asset_native_id), [])
        seen_alert_ids = set()
        for alt_data in alerts:
            alert_id = str(
                alt_data.get("_record_id")
                or alt_data.get("id")
                or alt_data.get("alert_id")
                or alt_data.get("native_id")
                or uuid.uuid4()
            )
            native_id = str(alt_data.get("native_id") or alt_data.get("alert_id") or alert_id)
            if native_id in seen_alert_ids or alert_id in seen_alert_ids:
                continue
            seen_alert_ids.add(native_id)
            seen_alert_ids.add(alert_id)

            chain.nodes.append(
                ChainNode(
                    id=alert_id,
                    record_type="alerts",
                    native_id=native_id,
                    label=f"Alert: {alt_data.get('title', 'Untitled')}",
                    timestamp=alt_data.get("timestamp") or alt_data.get("created_at"),
                    details=alt_data,
                ).__dict__
            )
            chain.edges.append(
                ChainEdge(
                    source_id=ast_node_id,
                    target_id=alert_id,
                    link_type="alert_observed",
                ).__dict__
            )
            alt_ts = alt_data.get("timestamp") or alt_data.get("created_at")
            if alt_ts:
                chain.timeline.append(
                    {
                        "event": f"Alert: {alt_data.get('title', 'Untitled')}",
                        "timestamp": alt_ts,
                        "record_type": "alerts",
                        "record_id": alert_id,
                    }
                )

        # Filter edges to valid nodes and deduplicate edges
        node_ids = {n["id"] for n in chain.nodes}
        seen_edges = set()
        valid_edges = []
        for e in chain.edges:
            if e["source_id"] in node_ids and e["target_id"] in node_ids:
                edge_key = (e["source_id"], e["target_id"], e.get("link_type"))
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    valid_edges.append(e)
        chain.edges = valid_edges

        chain.timeline.sort(key=lambda x: x["timestamp"] or "")
        return chain

    def get_full_evidence_chain(self, object_id: str) -> dict[str, Any]:
        """Builds an interactive evidence chain summary, timeline, and omissions for an object."""
        # Check if case
        is_case = (
            object_id in self.case_actions
            or object_id in self.case_to_alerts
            or any(
                str(c.get("native_id")) == str(object_id)
                or str(c.get("case_id")) == str(object_id)
                or str(c.get("id")) == str(object_id)
                for c in self.ctx.get_records("cases")
            )
            or (self.ctx.records_by_native_id.get(("cases", str(object_id))) is not None)
        )
        if is_case:
            chain = self.reconstruct_case_chain(object_id)
            obj_type = "case"
        else:
            chain = self.reconstruct_asset_chain(object_id)
            obj_type = "asset"

        return {
            "object_id": object_id,
            "object_type": obj_type,
            "summary": {
                "nodes_count": len(chain.nodes),
                "edges_count": len(chain.edges),
                "events_count": len(chain.timeline),
                "omissions_count": len(chain.omissions),
                "uncertainties_count": len(chain.uncertainties),
            },
            "timeline": [
                {
                    "timestamp": ev.get("timestamp"),
                    "entity_type": ev.get("record_type", "event"),
                    "entity_id": ev.get("record_id", object_id),
                    "event": ev.get("event", ""),
                    "source_reference": ev.get("source_reference"),
                }
                for ev in chain.timeline
            ],
            "related_entities": {
                "nodes": chain.nodes,
                "edges": chain.edges,
            },
            "uncertainties": chain.uncertainties,
            "omissions": chain.omissions,
        }

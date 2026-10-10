"""Reviewable per-job resume plans and their deterministic binding contract.

This module validates drafts and compares version bindings. It never records an
Owner approval or authorizes resume generation by itself.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


class PlanError(ValueError):
    """A plan cannot safely be presented as a complete V-0 plan."""


SCHEMA = "resume-tailoring-plan@1"
PROTECTED_SIGNAL_IDS = frozenset({"ID-PLATFORMS", "ID-PROJECTS", "ID-PROVENANCE"})
INPUT_SNAPSHOT_FIELDS = (
    "campaign_id", "campaign_revision", "job_id", "jd_revision", "jd_sha256",
    "research_revision", "master_sha256", "resume_profile_revision",
    "project_inventory_revision",
)
APPROVAL_INPUT_FIELDS = tuple(field for field in INPUT_SNAPSHOT_FIELDS if field not in {"campaign_id", "job_id"})
BUSINESS_FIELDS = (
    "strategy", "constraints", "section_plan", "project_plan",
    "protected_signal_plan", "layout_plan", "risks", "order_change_proposal",
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanError(f"{name} must be an object")
    return value


def _nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{name} must be nonempty text")
    return value.strip()


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 1:
        raise PlanError(f"{name} must be a positive integer")
    return value


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise PlanError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _refs(value: Any, name: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise PlanError(f"{name} must be a {'nonempty ' if nonempty else ''}list")
    if any(not isinstance(ref, str) or not ref.strip() for ref in value):
        raise PlanError(f"{name} contains an empty reference")
    if len(value) != len(set(value)):
        raise PlanError(f"{name} contains duplicate references")
    return value


def canonical_sha256(value: Any) -> str:
    """Hash JSON data independent of mapping insertion order and whitespace."""
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PlanError("value is not canonical JSON data") from exc
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def build_input_snapshot(plan: dict[str, Any]) -> dict[str, Any]:
    """Extract the exact input references whose change invalidates a plan approval."""
    plan = _mapping(plan, "plan")
    job = _mapping(plan.get("job_ref"), "job_ref")
    refs = _mapping(plan.get("input_refs"), "input_refs")
    snapshot = {
        "campaign_id": _nonempty(plan.get("campaign_id"), "campaign_id"),
        "campaign_revision": _positive_int(refs.get("campaign_revision"), "campaign_revision"),
        "job_id": _nonempty(job.get("job_id"), "job_id"),
        "jd_revision": _positive_int(job.get("jd_revision"), "jd_revision"),
        "jd_sha256": _digest(refs.get("jd_sha256"), "jd_sha256"),
        "research_revision": _positive_int(refs.get("research_revision"), "research_revision"),
        "master_sha256": _digest(refs.get("master_sha256"), "master_sha256"),
        "resume_profile_revision": _positive_int(refs.get("resume_profile_revision"), "resume_profile_revision"),
        "project_inventory_revision": _positive_int(refs.get("project_inventory_revision"), "project_inventory_revision"),
    }
    return snapshot


def input_snapshot_sha256(snapshot: dict[str, Any]) -> str:
    """Hash only the fixed input fields; reject omissions and ambiguous extras."""
    snapshot = _mapping(snapshot, "input snapshot")
    if set(snapshot) != set(INPUT_SNAPSHOT_FIELDS):
        raise PlanError("input snapshot must contain exactly the fixed input reference fields")
    _nonempty(snapshot["campaign_id"], "campaign_id")
    _nonempty(snapshot["job_id"], "job_id")
    for field in ("campaign_revision", "jd_revision", "research_revision", "resume_profile_revision", "project_inventory_revision"):
        _positive_int(snapshot[field], field)
    for field in ("jd_sha256", "master_sha256"):
        _digest(snapshot[field], field)
    return canonical_sha256(snapshot)


def plan_content_sha256(plan: dict[str, Any]) -> str:
    """Hash Owner-reviewed business fields, excluding UI/status/runtime metadata."""
    plan = _mapping(plan, "plan")
    missing = [field for field in BUSINESS_FIELDS if field not in plan and field != "order_change_proposal"]
    if missing:
        raise PlanError(f"plan business fields missing: {', '.join(missing)}")
    content = {field: plan[field] for field in BUSINESS_FIELDS if field in plan}
    content.setdefault("order_change_proposal", [])
    return canonical_sha256(content)


def _validate_order_proposals(plan: dict[str, Any], inventory_ids: list[str]) -> None:
    constraints = plan["constraints"]
    projects = plan["project_plan"]
    proposed_ids = [item["project_id"] for item in projects]
    needs: set[str] = set()
    if proposed_ids != inventory_ids or constraints.get("preserve_project_order") is False:
        needs.add("project")
    if (proposed_ids == inventory_ids) != constraints.get("preserve_project_order"):
        raise PlanError("preserve_project_order contradicts the proposed project sequence")
    if constraints.get("preserve_section_order") is False or any(
        row.get("preserve_order") is False for row in plan["section_plan"]
    ):
        needs.add("section")
    if constraints.get("preserve_retained_bullet_order") is False:
        needs.add("bullet")
    proposals = plan.get("order_change_proposal", [])
    if not isinstance(proposals, list):
        raise PlanError("order_change_proposal must be a list")
    seen: set[str] = set()
    for row in proposals:
        row = _mapping(row, "order change proposal")
        kind = row.get("kind")
        if kind not in {"project", "section", "bullet"} or kind in seen:
            raise PlanError("order change proposal kind is invalid or duplicated")
        seen.add(kind)
        _nonempty(row.get("rationale"), "order change rationale")
        before = _refs(row.get("original_order"), "original_order", nonempty=True)
        after = _refs(row.get("proposed_order"), "proposed_order", nonempty=True)
        if set(before) != set(after) or before == after:
            raise PlanError("order change must explicitly describe a permutation")
        if kind == "project" and (before != inventory_ids or after != proposed_ids):
            raise PlanError("project order proposal does not match inventory and plan")
    if needs != seen:
        raise PlanError("every order change needs an explicit proposal; unchanged order needs none")


def validate_tailoring_plan(
    plan: dict[str, Any], project_inventory: list[dict[str, Any]],
    jd_source: dict[str, Any], evidence_catalog: dict[str, Any],
    current_input_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Validate one pre-G2 plan against confirmed inventory and a complete JD.

    ``project_inventory`` is the Owner-confirmed required-display subset, not
    the raw candidate list. A valid result is a reviewable draft, not an
    approval, semantic factual audit, or PDF QA.
    A proposed reorder still needs separate Owner approval at G2.
    """
    plan = _mapping(plan, "plan")
    if plan.get("schema") != SCHEMA:
        raise PlanError(f"schema must be {SCHEMA}")
    _nonempty(plan.get("plan_id"), "plan_id")
    _positive_int(plan.get("plan_revision"), "plan_revision")
    snapshot = build_input_snapshot(plan)
    input_snapshot_sha256(current_input_snapshot)
    if snapshot != current_input_snapshot:
        changed = [field for field in INPUT_SNAPSHOT_FIELDS if snapshot[field] != current_input_snapshot[field]]
        raise PlanError(f"plan input refs differ from Host current input: {', '.join(changed)}")
    jd_source = _mapping(jd_source, "jd_source")
    if jd_source.get("completeness") != "FULL":
        raise PlanError("formal plan requires a FULL JD")
    jd_body = jd_source.get("body")
    _nonempty(jd_body, "full JD body")
    if not jd_source.get("source_url") and jd_source.get("owner_confirmed") is not True:
        raise PlanError("full JD needs a verifiable source URL or confirmed Owner text")
    if jd_source.get("job_id") != snapshot["job_id"] or jd_source.get("revision") != snapshot["jd_revision"]:
        raise PlanError("JD identity/revision differs from plan")
    if hashlib.sha256(jd_body.encode("utf-8")).hexdigest() != snapshot["jd_sha256"]:
        raise PlanError("full JD body hash differs from plan")
    jd_ids = _refs(jd_source.get("requirement_ids"), "JD requirement IDs", nonempty=True)
    evidence_catalog = _mapping(evidence_catalog, "evidence_catalog")
    business_ids = set(_refs(evidence_catalog.get("business_evidence_refs"), "verified business evidence refs", nonempty=True))
    fde_ids = set(_refs(evidence_catalog.get("fde_map_refs"), "verified FDE map refs", nonempty=True))
    owner_ids = set(_refs(evidence_catalog.get("owner_evidence_refs"), "verified Owner evidence refs", nonempty=True))

    strategy = _mapping(plan.get("strategy"), "strategy")
    _nonempty(strategy.get("summary"), "strategy.summary")
    business_refs = _refs(strategy.get("business_evidence_refs"), "business evidence refs", nonempty=True)
    strategy_jd = _refs(strategy.get("jd_requirement_refs"), "strategy JD refs", nonempty=True)
    fde_refs = _refs(strategy.get("fde_map_refs"), "FDE map refs", nonempty=True)
    if not set(strategy_jd) <= set(jd_ids):
        raise PlanError("strategy references requirements outside the complete JD")
    if not set(business_refs) <= business_ids or not set(fde_refs) <= fde_ids:
        raise PlanError("strategy references unverified company/FDE evidence")

    constraints = _mapping(plan.get("constraints"), "constraints")
    for key in ("all_projects_must_appear", "prefer_sentence_compression"):
        if constraints.get(key) is not True:
            raise PlanError(f"{key} must be true")
    if constraints.get("allow_project_drop") is not False:
        raise PlanError("whole-project DROP is forbidden")
    for key in ("preserve_section_order", "preserve_project_order", "preserve_retained_bullet_order"):
        if type(constraints.get(key)) is not bool:
            raise PlanError(f"{key} must explicitly be boolean")
    if constraints.get("target_pages") != 2:
        raise PlanError("target_pages must be 2")
    if constraints.get("hero_project_min") != 3 or constraints.get("hero_project_max") != 4:
        raise PlanError("HERO range must be 3–4")
    if constraints.get("compact_project_lines") != {"min": 1, "max": 2}:
        raise PlanError("COMPACT projects must target 1–2 lines")
    if set(_refs(constraints.get("protected_signal_ids"), "protected signal IDs")) != PROTECTED_SIGNAL_IDS:
        raise PlanError("all three protected identity signals must be retained")

    if not isinstance(project_inventory, list) or len(project_inventory) < 3:
        raise PlanError("confirmed project inventory needs at least three distinct projects")
    inventory: list[tuple[int, str]] = []
    for item in project_inventory:
        item = _mapping(item, "inventory project")
        if item.get("include_in_resume") is not True:
            raise PlanError("project_inventory must contain only Owner-confirmed required-display projects")
        inventory.append((_positive_int(item.get("original_index"), "inventory original_index"),
                          _nonempty(item.get("project_id"), "inventory project_id")))
    if len({i for i, _ in inventory}) != len(inventory) or len({p for _, p in inventory}) != len(inventory):
        raise PlanError("inventory IDs and source orders must be unique")
    inventory_ids = [pid for _, pid in sorted(inventory)]
    rows = plan.get("project_plan")
    if not isinstance(rows, list) or len(rows) != len(inventory_ids):
        raise PlanError("project plan must cover the complete inventory")
    planned_ids: list[str] = []
    heroes = 0
    for row in rows:
        row = _mapping(row, "project plan row")
        pid = _nonempty(row.get("project_id"), "project_id")
        planned_ids.append(pid)
        source_order = _positive_int(row.get("source_order"), f"{pid} source_order")
        if source_order != dict((p, n) for n, p in inventory).get(pid):
            raise PlanError(f"source_order does not match inventory for {pid}")
        tier = row.get("tier")
        if tier not in {"HERO", "COMPACT"}:
            raise PlanError(f"{pid} tier must be HERO or COMPACT")
        _nonempty(row.get("rationale"), f"{pid} rationale")
        project_evidence = _refs(row.get("owner_evidence_refs"), f"{pid} Owner evidence refs", nonempty=True)
        if not set(project_evidence) <= owner_ids:
            raise PlanError(f"{pid} references unverified Owner evidence")
        project_jd = _refs(row.get("jd_requirement_refs"), f"{pid} JD refs")
        if not set(project_jd) <= set(jd_ids):
            raise PlanError(f"{pid} references requirements outside the complete JD")
        if row.get("include_purpose") is not True or row.get("include_stack") is not True:
            raise PlanError(f"{pid} must retain purpose and core stack")
        if tier == "HERO":
            heroes += 1
            if type(row.get("target_bullets")) is not int or not 2 <= row["target_bullets"] <= 4:
                raise PlanError(f"{pid} HERO target_bullets must be 2–4")
        elif type(row.get("target_lines")) is not int or not 1 <= row["target_lines"] <= 2:
            raise PlanError(f"{pid} COMPACT target_lines must be 1–2")
    if len(planned_ids) != len(set(planned_ids)) or set(planned_ids) != set(inventory_ids):
        raise PlanError("project ID set must exactly match the confirmed inventory")
    if heroes not in {3, 4}:
        raise PlanError("plan must have 3–4 HERO projects")

    section_plan = plan.get("section_plan")
    if not isinstance(section_plan, list) or not section_plan:
        raise PlanError("section_plan must be nonempty")
    section_ids: set[str] = set()
    for row in section_plan:
        row = _mapping(row, "section plan row")
        sid = _nonempty(row.get("section_id"), "section_id")
        if sid in section_ids:
            raise PlanError("section_id must be unique")
        section_ids.add(sid)
        if row.get("action") not in {"KEEP", "COMPRESS", "MERGE"}:
            raise PlanError("section action must be KEEP, COMPRESS, or MERGE")
        if type(row.get("preserve_order")) is not bool:
            raise PlanError("section preserve_order must be boolean")
        _nonempty(row.get("rationale"), f"{sid} rationale")
        section_evidence = _refs(row.get("evidence_refs"), f"{sid} evidence refs", nonempty=True)
        if not set(section_evidence) <= owner_ids:
            raise PlanError(f"{sid} references unverified Owner evidence")
    if "internship" not in section_ids:
        raise PlanError("internship preservation/compression plan is required")
    _validate_order_proposals(plan, inventory_ids)

    signal_plan = _mapping(plan.get("protected_signal_plan"), "protected_signal_plan")
    if set(signal_plan) != PROTECTED_SIGNAL_IDS:
        raise PlanError("protected signal plan must explain all three identity signals")
    for signal_id, item in signal_plan.items():
        item = _mapping(item, signal_id)
        if item.get("action") not in {"KEEP", "REFRAME_WITH_FACTS"}:
            raise PlanError(f"{signal_id} protected signal action must retain the signal")
        _nonempty(item.get("handling"), f"{signal_id} handling")
        _nonempty(item.get("target_section"), f"{signal_id} target_section")
        signal_evidence = _refs(item.get("owner_evidence_refs"), f"{signal_id} Owner evidence refs", nonempty=True)
        if not set(signal_evidence) <= owner_ids:
            raise PlanError(f"{signal_id} references unverified Owner evidence")

    layout = _mapping(plan.get("layout_plan"), "layout_plan")
    _nonempty(layout.get("template_id"), "template_id")
    _nonempty(layout.get("renderer_id"), "renderer_id")
    if layout.get("page_size") != "A4" or layout.get("target_pages") != 2:
        raise PlanError("layout must target two A4 pages")
    font = layout.get("font_size_pt")
    bounds = layout.get("font_adjustment_range_pt")
    if isinstance(font, bool) or not isinstance(font, (int, float)) or not isinstance(bounds, list) or len(bounds) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in bounds) or not (0 < bounds[0] <= font <= bounds[1]):
        raise PlanError("font size must fit the proposed positive adjustment range")
    if not isinstance(plan.get("risks"), list):
        raise PlanError("risks must be a list, even when empty")
    review = _mapping(plan.get("review_projection"), "review_projection")
    if review.get("status") != "PENDING" or review.get("approval_ref") is not None:
        raise PlanError("draft cannot self-assert approval")

    return {
        "plan_id": plan["plan_id"], "plan_revision": plan["plan_revision"],
        "project_count": len(inventory_ids), "hero_count": heroes,
        "evidence_ref_integrity_checked": True,
        "input_snapshot": snapshot,
        "input_snapshot_sha256": input_snapshot_sha256(snapshot),
        "plan_content_sha256": plan_content_sha256(plan),
        "order_change_requires_separate_approval": bool(plan.get("order_change_proposal")),
    }


def check_plan_binding(approval_target: dict[str, Any], plan: dict[str, Any], current_input_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Compare a stored target with current data; MATCH is not an Owner action."""
    target = _mapping(approval_target, "approval target")
    plan = _mapping(plan, "plan")
    original = build_input_snapshot(plan)
    current_digest = input_snapshot_sha256(current_input_snapshot)
    differences: list[str] = []
    if target.get("plan_id") != plan.get("plan_id"):
        differences.append("plan_id")
    if target.get("plan_revision") != plan.get("plan_revision"):
        differences.append("plan_revision")
    if target.get("plan_content_sha256") != plan_content_sha256(plan):
        differences.append("plan_content_sha256")
    if target.get("input_snapshot_sha256") != input_snapshot_sha256(original):
        differences.append("approved_input_snapshot_sha256")
    if target.get("input_snapshot_sha256") != current_digest:
        differences.append("current_input_snapshot_sha256")
    for field in INPUT_SNAPSHOT_FIELDS:
        if original[field] != current_input_snapshot[field]:
            differences.append(field)
        if field in APPROVAL_INPUT_FIELDS and target.get(field) != original[field]:
            differences.append(f"approval_target.{field}")
    return {"status": "STALE" if differences else "MATCH", "differences": differences}

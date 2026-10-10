from __future__ import annotations

import copy
import hashlib
import unittest

from career_v0.plans import (
    PlanError,
    build_input_snapshot,
    check_plan_binding,
    input_snapshot_sha256,
    plan_content_sha256,
    validate_tailoring_plan as _validate_tailoring_plan,
)


JD_BODY = "岗位职责：设计 Agent 工作流。要求：Python、RAG 和评测。"
JD_HASH = hashlib.sha256(JD_BODY.encode("utf-8")).hexdigest()
MASTER_HASH = "a" * 64
INVENTORY = [{"project_id": f"PRJ-{n}", "original_index": n, "include_in_resume": True} for n in range(1, 8)]
JD_SOURCE = {
    "job_id": "JOB-1", "revision": 1, "completeness": "FULL",
    "body": JD_BODY, "source_url": "https://example.org/job/1",
    "requirement_ids": ["JD-R1", "JD-R2"],
}
EVIDENCE_CATALOG = {
    "business_evidence_refs": ["COMPANY-1"], "fde_map_refs": ["FDE-1"],
    "owner_evidence_refs": [
        *(f"MASTER-PRJ-{n}" for n in range(1, 8)), "MASTER-INTERN-1",
        "PROFILE-ID-PLATFORMS", "PROFILE-ID-PROJECTS", "PROFILE-ID-PROVENANCE",
    ],
}
CURRENT_INPUT = {
    "campaign_id": "CMP-1", "campaign_revision": 1, "job_id": "JOB-1",
    "jd_revision": 1, "jd_sha256": JD_HASH, "research_revision": 1,
    "master_sha256": MASTER_HASH, "resume_profile_revision": 1,
    "project_inventory_revision": 1,
}


def validate_tailoring_plan(plan_value, inventory=INVENTORY, jd_source=JD_SOURCE):
    return _validate_tailoring_plan(plan_value, inventory, jd_source, EVIDENCE_CATALOG, CURRENT_INPUT)


def plan() -> dict:
    return {
        "schema": "resume-tailoring-plan@1", "plan_id": "PLAN-JOB-1", "plan_revision": 1,
        "campaign_id": "CMP-1", "job_ref": {"job_id": "JOB-1", "jd_revision": 1},
        "input_refs": {
            "campaign_revision": 1, "jd_sha256": JD_HASH, "master_sha256": MASTER_HASH,
            "resume_profile_revision": 1, "project_inventory_revision": 1,
            "research_revision": 1,
        },
        "strategy": {
            "summary": "为 Agent 岗位突出工作流与评测证据",
            "business_evidence_refs": ["COMPANY-1"],
            "jd_requirement_refs": ["JD-R1", "JD-R2"],
            "fde_map_refs": ["FDE-1"],
        },
        "constraints": {
            "target_pages": 2, "preserve_section_order": True,
            "preserve_project_order": True, "preserve_retained_bullet_order": True,
            "all_projects_must_appear": True, "hero_project_min": 3,
            "hero_project_max": 4, "compact_project_lines": {"min": 1, "max": 2},
            "allow_project_drop": False, "prefer_sentence_compression": True,
            "protected_signal_ids": ["ID-PLATFORMS", "ID-PROJECTS", "ID-PROVENANCE"],
        },
        "section_plan": [{
            "section_id": "internship", "action": "COMPRESS", "preserve_order": True,
            "target_bullets": 2, "rationale": "给完整项目清单留空间",
            "evidence_refs": ["MASTER-INTERN-1"],
        }],
        "project_plan": [{
            "project_id": f"PRJ-{n}", "source_order": n,
            "tier": "HERO" if n <= 3 else "COMPACT",
            "target_bullets": 3 if n <= 3 else None,
            "target_lines": None if n <= 3 else 2,
            "include_purpose": True, "include_stack": True,
            "rationale": "岗位相关" if n <= 3 else "保留项目地图",
            "emphasis": ["Agent"],
            "jd_requirement_refs": ["JD-R1"] if n <= 3 else [],
            "owner_evidence_refs": [f"MASTER-PRJ-{n}"],
        } for n in range(1, 8)],
        "protected_signal_plan": {
            signal: {
                "action": "KEEP", "handling": "保留已确认措辞", "target_section": "highlights",
                "owner_evidence_refs": [f"PROFILE-{signal}"],
            } for signal in ("ID-PLATFORMS", "ID-PROJECTS", "ID-PROVENANCE")
        },
        "layout_plan": {
            "template_id": "TPL-1", "renderer_id": "PENDING_SPIKE",
            "page_size": "A4", "target_pages": 2,
            "font_size_pt": 10.5, "font_adjustment_range_pt": [10.0, 11.0],
            "allow_density_adjustment": True,
        },
        "risks": [], "order_change_proposal": [],
        "review_projection": {"status": "PENDING", "approval_ref": None},
    }


class TailoringPlanContractTests(unittest.TestCase):
    def test_valid_plan_covers_confirmed_inventory_and_full_jd(self):
        result = validate_tailoring_plan(plan(), INVENTORY, JD_SOURCE)
        self.assertEqual((result["project_count"], result["hero_count"]), (7, 3))
        self.assertEqual(len(result["input_snapshot_sha256"]), 64)
        self.assertFalse(result["order_change_requires_separate_approval"])

    def test_missing_project_and_drop_are_rejected(self):
        edited = plan()
        edited["project_plan"].pop()
        with self.assertRaisesRegex(PlanError, "complete inventory"):
            validate_tailoring_plan(edited, INVENTORY, JD_SOURCE)
        edited = plan()
        edited["constraints"]["allow_project_drop"] = True
        with self.assertRaisesRegex(PlanError, "DROP"):
            validate_tailoring_plan(edited, INVENTORY, JD_SOURCE)
        unconfirmed = copy.deepcopy(INVENTORY)
        unconfirmed[-1]["include_in_resume"] = None
        with self.assertRaisesRegex(PlanError, "Owner-confirmed required-display"):
            validate_tailoring_plan(plan(), unconfirmed, JD_SOURCE)

    def test_hero_count_and_compact_content_are_enforced(self):
        edited = plan()
        edited["project_plan"][2]["tier"] = "COMPACT"
        edited["project_plan"][2]["target_lines"] = 2
        with self.assertRaisesRegex(PlanError, "3–4 HERO"):
            validate_tailoring_plan(edited, INVENTORY, JD_SOURCE)
        edited = plan()
        edited["project_plan"][4]["include_stack"] = False
        with self.assertRaisesRegex(PlanError, "purpose and core stack"):
            validate_tailoring_plan(edited, INVENTORY, JD_SOURCE)

    def test_protected_signals_need_both_constraints_and_handling(self):
        edited = plan()
        edited["constraints"]["protected_signal_ids"].pop()
        with self.assertRaisesRegex(PlanError, "protected identity"):
            validate_tailoring_plan(edited, INVENTORY, JD_SOURCE)
        edited = plan()
        del edited["protected_signal_plan"]["ID-PROVENANCE"]
        with self.assertRaisesRegex(PlanError, "all three identity"):
            validate_tailoring_plan(edited, INVENTORY, JD_SOURCE)

    def test_default_reorder_requires_explicit_separate_proposal(self):
        edited = plan()
        edited["project_plan"][0], edited["project_plan"][1] = edited["project_plan"][1], edited["project_plan"][0]
        edited["constraints"]["preserve_project_order"] = False
        with self.assertRaisesRegex(PlanError, "explicit proposal"):
            validate_tailoring_plan(edited, INVENTORY, JD_SOURCE)
        edited["order_change_proposal"] = [{
            "kind": "project", "rationale": "针对该岗位建议调整优先级",
            "original_order": [f"PRJ-{n}" for n in range(1, 8)],
            "proposed_order": [item["project_id"] for item in edited["project_plan"]],
        }]
        result = validate_tailoring_plan(edited, INVENTORY, JD_SOURCE)
        self.assertTrue(result["order_change_requires_separate_approval"])

    def test_incomplete_or_unverified_jd_cannot_form_formal_plan(self):
        partial = {**JD_SOURCE, "completeness": "PARTIAL"}
        with self.assertRaisesRegex(PlanError, "FULL JD"):
            validate_tailoring_plan(plan(), INVENTORY, partial)
        no_source = {**JD_SOURCE, "source_url": None}
        with self.assertRaisesRegex(PlanError, "verifiable source"):
            validate_tailoring_plan(plan(), INVENTORY, no_source)
        self.assertEqual(validate_tailoring_plan(plan(), INVENTORY, {**no_source, "owner_confirmed": True})["project_count"], 7)

    def test_jd_body_hash_and_requirement_refs_must_match(self):
        with self.assertRaisesRegex(PlanError, "body hash"):
            validate_tailoring_plan(plan(), INVENTORY, {**JD_SOURCE, "body": "Changed JD"})
        edited = plan()
        edited["project_plan"][0]["jd_requirement_refs"] = ["JD-R999"]
        with self.assertRaisesRegex(PlanError, "outside the complete JD"):
            validate_tailoring_plan(edited, INVENTORY, JD_SOURCE)

    def test_unknown_owner_evidence_ref_is_rejected(self):
        edited = plan()
        edited["project_plan"][0]["owner_evidence_refs"] = ["MASTER-NONEXISTENT"]
        with self.assertRaisesRegex(PlanError, "unverified Owner evidence"):
            validate_tailoring_plan(edited, INVENTORY, JD_SOURCE)
        edited = plan()
        edited["strategy"]["business_evidence_refs"] = ["COMPANY-NONEXISTENT"]
        with self.assertRaisesRegex(PlanError, "unverified company/FDE evidence"):
            validate_tailoring_plan(edited, INVENTORY, JD_SOURCE)

    def test_draft_cannot_self_assert_approval(self):
        edited = plan()
        edited["review_projection"] = {"status": "APPROVED", "approval_ref": "APR-FAKE"}
        with self.assertRaisesRegex(PlanError, "self-assert approval"):
            validate_tailoring_plan(edited, INVENTORY, JD_SOURCE)

    def test_business_hash_ignores_key_order_and_runtime_metadata(self):
        base = plan()
        flipped = copy.deepcopy(base)
        flipped["strategy"] = dict(reversed(list(flipped["strategy"].items())))
        flipped["updated_at"] = "irrelevant"
        flipped["review_projection"] = {"status": "REQUEST_CHANGES", "approval_ref": None}
        self.assertEqual(plan_content_sha256(base), plan_content_sha256(flipped))
        flipped["project_plan"][0]["tier"] = "COMPACT"
        self.assertNotEqual(plan_content_sha256(base), plan_content_sha256(flipped))
        omitted_empty_proposal = copy.deepcopy(base)
        del omitted_empty_proposal["order_change_proposal"]
        self.assertEqual(plan_content_sha256(base), plan_content_sha256(omitted_empty_proposal))

    def test_input_snapshot_ignores_extra_plan_metadata_and_rejects_missing_ref(self):
        base = plan()
        shifted = copy.deepcopy(base)
        shifted["tool_trace"] = {"token_count": 100}
        self.assertEqual(input_snapshot_sha256(build_input_snapshot(base)),
                         input_snapshot_sha256(build_input_snapshot(shifted)))
        del shifted["input_refs"]["master_sha256"]
        with self.assertRaisesRegex(PlanError, "master_sha256"):
            build_input_snapshot(shifted)

    def test_plan_cannot_claim_a_different_host_input_revision(self):
        edited = plan()
        edited["input_refs"]["resume_profile_revision"] = 2
        with self.assertRaisesRegex(PlanError, "Host current input: resume_profile_revision"):
            validate_tailoring_plan(edited, INVENTORY, JD_SOURCE)

    def test_binding_stales_on_business_or_input_changes(self):
        base = plan()
        source = build_input_snapshot(base)
        target = {
            "plan_id": base["plan_id"], "plan_revision": base["plan_revision"],
            "plan_content_sha256": plan_content_sha256(base),
            "input_snapshot_sha256": input_snapshot_sha256(source),
            **{key: value for key, value in source.items() if key not in {"campaign_id", "job_id"}},
        }
        self.assertEqual(check_plan_binding(target, base, source)["status"], "MATCH")
        for field, value in (
            ("jd_sha256", "b" * 64), ("master_sha256", "b" * 64),
            ("resume_profile_revision", 2), ("project_inventory_revision", 2),
            ("research_revision", 2), ("campaign_revision", 2),
        ):
            current = {**source, field: value}
            self.assertEqual(check_plan_binding(target, base, current)["status"], "STALE", field)
        modified = copy.deepcopy(base)
        modified["layout_plan"]["template_id"] = "TPL-2"
        self.assertEqual(check_plan_binding(target, modified, source)["status"], "STALE")
        modified = copy.deepcopy(base)
        modified["plan_revision"] = 2
        self.assertEqual(check_plan_binding(target, modified, source)["status"], "STALE")
        missing_binding = dict(target)
        del missing_binding["master_sha256"]
        self.assertIn("approval_target.master_sha256", check_plan_binding(missing_binding, base, source)["differences"])


if __name__ == "__main__":
    unittest.main()

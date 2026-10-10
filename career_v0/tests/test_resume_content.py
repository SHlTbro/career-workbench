from __future__ import annotations

import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from career_v0.resume_content import ResumeContentError, build_resume_content, content_html
from career_v0.resume_render import render_and_inspect
from career_v0.service import CareerService
from career_v0.tests.test_m1 import SYNTHETIC_MASTER, preferences
from career_v0.tests.test_plans import plan as plan_fixture


class ResumeContentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.master = Path(self.tmp.name) / "master.md"
        self.master.write_bytes(SYNTHETIC_MASTER)
        self.service = CareerService(Path(self.tmp.name) / "state", master_path=self.master,
                                     allow_simulated_owner=True)
        self.service.create_campaign(preferences(), campaign_id="CMP-RESUME")
        self.campaign = self.service.confirm_campaign("CMP-RESUME", actor_channel="SIMULATED_OWNER_TEST")
        self.plan = plan_fixture()
        self.plan["project_plan"] = []
        for index, item in enumerate(self.campaign["project_inventory"]["projects"]):
            self.plan["project_plan"].append({"project_id": item["project_id"],
                "tier": "HERO" if index < 3 else "COMPACT", "target_bullets": 2,
                "source_order": item["original_index"], "emphasis": []})

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_projects_and_protected_signals_render_in_source_order(self):
        content = build_resume_content(SYNTHETIC_MASTER, self.campaign, self.plan)
        self.assertEqual(content["project_ids"], self.campaign["resume_profile"]["required_project_ids"])
        self.assertEqual(sum(row["tier"] == "HERO" for row in content["projects"]), 3)
        markup = content_html(content, self.plan)
        for project_id in content["project_ids"]:
            self.assertIn(f"data-project-id='{project_id}'", markup)
        self.assertIn("10+ AI 平台", markup)
        self.assertIn("7+ AI 项目", markup)
        self.assertIn("开发过程留痕", markup)

    def test_unapproved_reorder_is_not_silently_applied(self):
        self.plan["project_plan"][0], self.plan["project_plan"][1] = (
            self.plan["project_plan"][1], self.plan["project_plan"][0])
        with self.assertRaisesRegex(ResumeContentError, "order differs"):
            build_resume_content(SYNTHETIC_MASTER, self.campaign, self.plan)

    def test_sparse_synthetic_pdf_is_not_accepted_as_two_page_candidate(self):
        content = build_resume_content(SYNTHETIC_MASTER, self.campaign, self.plan)
        source = Path(self.tmp.name) / "synthetic.html"
        pdf = Path(self.tmp.name) / "synthetic.pdf"
        source.write_text(content_html(content, self.plan), encoding="utf-8")
        with patch.dict("os.environ", {"CAREER_NODE_BIN": shutil.which("node") or ""}):
            qa = render_and_inspect(source, pdf, expected_project_ids=content["project_ids"],
                                    expected_text=[content["name"], *[row["name"] for row in content["projects"]]])
        self.assertEqual(qa["status"], "NEEDS_PLAN_REVISION")
        self.assertIn("PAGE_COUNT_1_EXPECTED_2", qa["problems"])


if __name__ == "__main__":
    unittest.main()

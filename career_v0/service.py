"""M1 business actions. File uploads are previews until a Host Owner action confirms them."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable

import pdfplumber

from .domain import DomainError, make_batch, stable_hash, utc_now, validate_campaign_preferences
from .discovery import ground_job, parse_dsh_events, source_records
from .inventory import candidate_inventory, validate_confirmed_inventory
from .research import ResearchError, attach_company_dossier, selected_source_dossier, validate_research_dossier
from .profile import build_resume_profile, validate_identity_signals
from .plans import PlanError, check_plan_binding, validate_tailoring_plan
from .plan_workbooks import export_plan_workbook, import_plan_workbook
from .resume_content import build_resume_content, content_html
from .resume_render import render_and_inspect
from .store import JsonStore, StoreError
from .workbooks import export_candidate_workbook, import_candidate_workbook


class CareerService:
    def __init__(self, state_dir: str | Path, *, master_path: str | Path | None = None,
                 allow_simulated_owner: bool = False,
                 owner_action_verifier: Callable[[str], bool] | None = None):
        self.store = JsonStore(state_dir)
        self.artifacts = self.store.root / "artifacts"
        self.artifacts.mkdir(exist_ok=True)
        self.allow_simulated_owner = allow_simulated_owner
        self.owner_action_verifier = owner_action_verifier
        self.master_path = Path(master_path).resolve() if master_path else None

    @staticmethod
    def _job_record_key(batch_id: str, job_id: str) -> str:
        return "BJ-" + stable_hash([batch_id, job_id])[:24].upper()

    @staticmethod
    def _company_record_key(campaign_id: str, company: str) -> str:
        return "COMP-" + stable_hash([campaign_id, company.casefold().strip()])[:24].upper()

    def inventory_candidate(self) -> dict[str, Any]:
        if self.master_path is None or not self.master_path.is_file():
            raise DomainError("master resume path is not configured")
        return candidate_inventory(self.master_path.read_bytes())

    def _require_current_master(self, campaign: dict[str, Any]) -> None:
        if self.master_path is None or not self.master_path.is_file():
            raise DomainError("master resume path is not configured")
        if hashlib.sha256(self.master_path.read_bytes()).hexdigest() != campaign.get("master_sha256"):
            raise DomainError("master changed after G0; confirm a new Campaign revision")

    def _owner(self, actor_channel: str) -> str:
        if isinstance(actor_channel, str) and actor_channel.startswith("OWNER_UI:"):
            proof = actor_channel.removeprefix("OWNER_UI:")
            if proof and self.owner_action_verifier and self.owner_action_verifier(proof):
                return "OWNER"
        if actor_channel == "SIMULATED_OWNER_TEST" and self.allow_simulated_owner:
            return "SIMULATED_OWNER"
        raise DomainError("a real Host Owner action is required")

    def create_campaign(self, preferences: dict[str, Any], *, campaign_id: str | None = None) -> dict[str, Any]:
        if not isinstance(preferences, dict):
            raise DomainError("Campaign preferences draft must be an object")
        campaign_id = campaign_id or "CMP-" + uuid.uuid4().hex[:20].upper()
        value = {"schema": "career-campaign@1", "campaign_id": campaign_id,
                 "revision": 1, "status": "PREFERENCE_DRAFT", "preferences": preferences,
                 "created_at": utc_now(), "confirmed_by": None, "confirmed_at": None}
        return self.store.put_new("campaigns", campaign_id, value)

    def confirm_campaign(self, campaign_id: str, *, actor_channel: str) -> dict[str, Any]:
        actor = self._owner(actor_channel)
        current = self.store.get("campaigns", campaign_id)
        if current is None:
            raise DomainError("campaign not found")
        if current["status"] == "PREFERENCE_CONFIRMED":
            self._require_current_master(current)
            return current
        validate_campaign_preferences(current["preferences"])
        master_bytes = self.master_path.read_bytes() if self.master_path else b""
        candidate = candidate_inventory(master_bytes)
        validate_confirmed_inventory(current["preferences"].get("project_inventory") or {}, candidate)
        validate_identity_signals(current["preferences"].get("identity_signals"), master_bytes)
        value = {**current, **current["preferences"], "revision": current["revision"] + 1,
                 "status": "PREFERENCE_CONFIRMED", "confirmed_by": actor,
                 "confirmed_at": utc_now(), "master_sha256": candidate["master_sha256"],
                 "project_inventory_sha256": stable_hash(current["preferences"]["project_inventory"])}
        value["resume_profile"] = build_resume_profile(value, master_bytes)
        return self.store.replace("campaigns", campaign_id, value, expected_revision=current["revision"])

    def revise_campaign(self, campaign_id: str, preferences: dict[str, Any], *, actor_channel: str) -> dict[str, Any]:
        actor = self._owner(actor_channel)
        current = self.store.get("campaigns", campaign_id)
        if current is None:
            raise DomainError("campaign not found")
        if not isinstance(preferences, dict):
            raise DomainError("Campaign preferences draft must be an object")
        if preferences == current["preferences"]:
            return current
        affected_batches = []
        for batch in self.store.list_records("batches"):
            if batch.get("campaign_id") == campaign_id and batch.get("campaign_revision") == current["revision"]:
                affected_batches.append(batch["batch_id"])
        revised = {"schema": "career-campaign@1", "campaign_id": campaign_id,
                   "revision": current["revision"] + 1, "status": "PREFERENCE_DRAFT",
                   "preferences": preferences, "created_at": current["created_at"],
                   "revised_at": utc_now(), "revised_by": actor,
                   "supersedes_revision": current["revision"],
                   "affected_batch_ids": sorted(affected_batches),
                   "confirmed_by": None, "confirmed_at": None}
        return self.store.replace("campaigns", campaign_id, revised, expected_revision=current["revision"])

    def ingest_discovery_trace(self, campaign_id: str, data: bytes, *,
                               purpose: str = "JOB_SOURCES", company: str | None = None) -> dict[str, Any]:
        campaign = self.store.get("campaigns", campaign_id)
        if campaign is None or campaign["status"] != "PREFERENCE_CONFIRMED":
            raise DomainError("G0 confirmation required before discovery")
        self._require_current_master(campaign)
        if purpose not in {"JOB_SOURCES", "COMPANY_RESEARCH"}:
            raise DomainError("discovery purpose invalid")
        if purpose == "COMPANY_RESEARCH" and (not isinstance(company, str) or not company.strip()):
            raise DomainError("company research needs the selected company name")
        record = source_records(parse_dsh_events(data))
        record.update({"discovery_id": "DIS-" + uuid.uuid4().hex[:20].upper(),
                       "campaign_id": campaign_id, "campaign_revision": campaign["revision"],
                       "purpose": purpose, "company": company if purpose == "COMPANY_RESEARCH" else None,
                       "revision": 1,
                       "trace_sha256": hashlib.sha256(data).hexdigest(), "created_at": utc_now()})
        record["artifact_path"] = str(self._write_artifact("discovery", record["discovery_id"] + ".jsonl", data))
        return self.store.put_new("discoveries", record["discovery_id"], record)

    def extend_discovery_trace(self, discovery_id: str, data: bytes) -> dict[str, Any]:
        current = self.store.get("discoveries", discovery_id)
        if current is None:
            raise DomainError("discovery trace not found")
        campaign = self.store.get("campaigns", current["campaign_id"])
        if campaign is None or campaign["revision"] != current["campaign_revision"]:
            raise DomainError("discovery campaign version is stale")
        self._require_current_master(campaign)
        existing = Path(current["artifact_path"]).read_bytes()
        if hashlib.sha256(existing).hexdigest() != current["trace_sha256"]:
            raise DomainError("stored discovery trace hash mismatch")
        merged = existing.rstrip(b"\r\n") + b"\n" + data.lstrip(b"\r\n")
        record = {**source_records(parse_dsh_events(merged)),
                  "discovery_id": discovery_id, "campaign_id": current["campaign_id"],
                  "campaign_revision": current["campaign_revision"],
                  "purpose": current.get("purpose", "JOB_SOURCES"), "company": current.get("company"),
                  "revision": current["revision"] + 1,
                  "trace_sha256": hashlib.sha256(merged).hexdigest(),
                  "created_at": current["created_at"], "updated_at": utc_now()}
        record["artifact_path"] = str(self._write_artifact("discovery", f"{discovery_id}-r{record['revision']}.jsonl", merged))
        return self.store.replace("discoveries", discovery_id, record, expected_revision=current["revision"])

    def create_batch(self, campaign_id: str, found_jobs: list[dict[str, Any]], *, batch_id: str | None = None,
                     discovery_id: str | None = None) -> dict[str, Any]:
        campaign = self.store.get("campaigns", campaign_id)
        if campaign is None:
            raise DomainError("campaign not found")
        if campaign["status"] != "PREFERENCE_CONFIRMED":
            raise DomainError("G0 confirmation required before discovery")
        self._require_current_master(campaign)
        if discovery_id:
            discovery = self.store.get("discoveries", discovery_id)
            if discovery is None or discovery["campaign_id"] != campaign_id or discovery["campaign_revision"] != campaign["revision"]:
                raise DomainError("discovery trace/campaign version mismatch")
            if discovery.get("purpose", "JOB_SOURCES") != "JOB_SOURCES":
                raise DomainError("company research discovery cannot create a candidate job batch")
            found_jobs = [ground_job(job, discovery) for job in found_jobs]
        elif not self.allow_simulated_owner:
            raise DomainError("DSH discovery trace required for production batch")
        batch_id = batch_id or "BAT-" + uuid.uuid4().hex[:20].upper()
        batch = make_batch(campaign, found_jobs, batch_id)
        batch["discovery_id"] = discovery_id
        batch["discovery_revision"] = discovery["revision"] if discovery_id else None
        return self.store.put_new("batches", batch_id, batch)

    def create_batch_from_normalizations(self, discovery_id: str, normalized_ids: list[str], *,
                                         batch_id: str | None = None) -> dict[str, Any]:
        discovery = self.store.get("discoveries", discovery_id)
        if discovery is None:
            raise DomainError("discovery trace not found")
        if not isinstance(normalized_ids, list) or not normalized_ids or len(set(normalized_ids)) != len(normalized_ids):
            raise DomainError("select unique normalized source IDs for a batch")
        captures = {cap["capture_id"]: cap for cap in discovery["captures"]}
        proposals = []
        for normalized_id in normalized_ids:
            item = self.store.get("normalized_jobs", normalized_id)
            if item is None or item["discovery_id"] != discovery_id or item["status"] != "CLASSIFIED_CANDIDATE":
                raise DomainError("normalized source is missing or unclassified")
            capture = captures.get(item["capture_id"])
            if capture is None or capture["raw_result_sha256"] != item["capture_sha256"]:
                raise DomainError("normalized source capture changed")
            proposals.append(item["proposed"])
        return self.create_batch(discovery["campaign_id"], proposals, batch_id=batch_id,
                                 discovery_id=discovery_id)

    def _write_artifact(self, folder: str, name: str, content: bytes) -> Path:
        target_dir = self.artifacts / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / name
        fd, temporary = tempfile.mkstemp(prefix=".career-", suffix=".tmp", dir=target_dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target

    def export_candidates(self, batch_id: str) -> tuple[Path, dict[str, Any]]:
        batch = self.store.get("batches", batch_id)
        if batch is None:
            raise DomainError("batch not found")
        campaign = self.store.get("campaigns", batch["campaign_id"])
        if campaign is None or campaign["revision"] != batch["campaign_revision"]:
            raise DomainError("batch campaign revision is stale")
        self._require_current_master(campaign)
        data, snapshot = export_candidate_workbook(campaign, batch)
        filename = f"candidate_jobs_{campaign['campaign_id']}_{batch_id}_{snapshot['export_id']}.xlsx"
        path = self._write_artifact("exports", filename, data)
        snapshot["workbook_sha256"] = hashlib.sha256(data).hexdigest()
        snapshot["artifact_path"] = str(path)
        self.store.put_new("exports", snapshot["export_id"], snapshot)
        return path, snapshot

    def preview_selection(self, export_id: str, data: bytes) -> dict[str, Any]:
        snapshot = self.store.get("exports", export_id)
        if snapshot is None:
            raise DomainError("unknown export_id")
        campaign = self.store.get("campaigns", snapshot["campaign_id"])
        batch = self.store.get("batches", snapshot["batch_id"])
        if campaign is None or campaign["revision"] != snapshot["campaign_revision"]:
            raise DomainError("workbook campaign revision is stale")
        self._require_current_master(campaign)
        if batch is None or batch["revision"] != snapshot["batch_revision"]:
            raise DomainError("workbook batch revision is stale")
        current_selection = self.store.get("selections", snapshot["batch_id"])
        previous = current_selection["selected_job_ids"] if current_selection else []
        preview = import_candidate_workbook(data, snapshot, previous_selected=previous)
        preview["selection_revision_at_preview"] = current_selection["revision"] if current_selection else 0
        preview["artifact_path"] = str(self._write_artifact("imports", preview["preview_id"] + ".xlsx", data))
        self.store.put_new("previews", preview["preview_id"], preview)
        return preview

    def confirm_selection(self, preview_id: str, *, actor_channel: str,
                          accept_shortfall: bool = False) -> dict[str, Any]:
        actor = self._owner(actor_channel)
        preview = self.store.get("previews", preview_id)
        if preview is None:
            raise DomainError("import preview not found")
        if not preview["selected_job_ids"]:
            raise DomainError("empty selection remains WAITING_JOB_SELECTION")
        campaign = self.store.get("campaigns", preview["campaign_id"])
        batch = self.store.get("batches", preview["batch_id"])
        if campaign is None or campaign["revision"] != preview["campaign_revision"]:
            raise DomainError("preview campaign revision is stale")
        self._require_current_master(campaign)
        if batch is None or batch["revision"] != preview["batch_revision"]:
            raise DomainError("preview batch revision is stale")
        if batch["target_shortfall"] > 0 and accept_shortfall is not True:
            raise DomainError("Owner must explicitly accept the smaller qualified batch before G1")
        snapshot = self.store.get("exports", preview["export_id"])
        if snapshot is None or snapshot["batch_revision"] != batch["revision"]:
            raise DomainError("preview export is stale")
        current = self.store.get("selections", preview["batch_id"])
        if current and current["file_sha256"] == preview["file_sha256"] and current["selected_job_ids"] == preview["selected_job_ids"]:
            return current
        if (current["revision"] if current else 0) != preview["selection_revision_at_preview"]:
            raise DomainError("selection changed after import preview; upload again")
        revision = current["revision"] + 1 if current else 1
        record = {
            "schema": "owner-selection@1", "selection_id": "SEL-" + uuid.uuid4().hex[:20].upper(),
            "revision": revision, "campaign_id": preview["campaign_id"],
            "campaign_revision": preview["campaign_revision"], "batch_id": preview["batch_id"],
            "batch_revision": preview["batch_revision"], "export_id": preview["export_id"],
            "import_id": preview_id, "file_sha256": preview["file_sha256"],
            "selected_job_ids": preview["selected_job_ids"], "owner_priority": preview["owner_priority"],
            "owner_note": preview["owner_note"], "confirmed_by": actor,
            "confirmed_at": utc_now(), "status": "JOB_SELECTION_CONFIRMED",
            "target_count": batch["target_count"],
            "qualified_count": batch["counts"]["qualified"],
            "shortfall_accepted": batch["target_shortfall"] > 0 and accept_shortfall is True,
        }
        if current:
            self.store.replace("selections", preview["batch_id"], record, expected_revision=current["revision"])
        else:
            self.store.put_new("selections", preview["batch_id"], record)
        self.store.put_new("selection_events", record["selection_id"], record)
        return record

    def selected_jobs(self, batch_id: str) -> list[dict[str, Any]]:
        selection = self.store.get("selections", batch_id)
        if selection is None or selection.get("status") != "JOB_SELECTION_CONFIRMED":
            raise DomainError("G1 confirmation required before deep research")
        batch = self.store.get("batches", batch_id)
        if batch is None or batch["revision"] != selection["batch_revision"]:
            raise DomainError("selection batch revision is stale")
        campaign = self.store.get("campaigns", selection["campaign_id"])
        if campaign is None or campaign["revision"] != selection["campaign_revision"]:
            raise DomainError("selection campaign revision is stale")
        self._require_current_master(campaign)
        return [batch["jobs"][job_id] for job_id in selection["selected_job_ids"]]

    def confirm_owner_jd(self, batch_id: str, job_id: str, body: str, *, actor_channel: str) -> dict[str, Any]:
        actor = self._owner(actor_channel)
        if job_id not in {job["job_id"] for job in self.selected_jobs(batch_id)}:
            raise DomainError("only G1-selected jobs may receive an Owner-confirmed JD")
        if not isinstance(body, str) or len(body.strip()) < 50:
            raise DomainError("Owner JD text is too short for a full description")
        record_key = self._job_record_key(batch_id, job_id)
        current = self.store.get("owner_jds", record_key)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if current and current["sha256"] == digest:
            return current
        value = {"schema": "owner-confirmed-jd@1", "job_id": job_id, "batch_id": batch_id,
                 "revision": current["revision"] + 1 if current else 1,
                 "body": body, "sha256": digest, "confirmed_by": actor, "confirmed_at": utc_now()}
        if current:
            return self.store.replace("owner_jds", record_key, value, expected_revision=current["revision"])
        return self.store.put_new("owner_jds", record_key, value)

    def prepare_selected_source_research(self, batch_id: str, job_id: str) -> dict[str, Any]:
        selected = {job["job_id"]: job for job in self.selected_jobs(batch_id)}
        if job_id not in selected:
            raise DomainError("G1 selection required for selected-source research")
        if self.store.get("research", self._job_record_key(batch_id, job_id)) is not None:
            raise DomainError("research already exists; revise it with new evidence instead of replacing silently")
        batch = self.store.get("batches", batch_id)
        discovery_id = batch.get("discovery_id")
        discovery = self.store.get("discoveries", discovery_id) if discovery_id else None
        job = selected[job_id]
        if discovery is None or discovery["campaign_id"] != batch["campaign_id"] or discovery["campaign_revision"] != batch["campaign_revision"]:
            raise DomainError("selected job has no matching DSH discovery trace")
        capture = next((cap for cap in discovery["captures"]
                        if cap["capture_id"] == job.get("source_capture_id")
                        and cap["raw_result_sha256"] == job.get("source_content_sha256")), None)
        if capture is None:
            raise DomainError("selected job JD source capture changed or is missing")
        dossier = selected_source_dossier(job, capture, discovery_id)
        company = self.store.get("company_dossiers", self._company_record_key(batch["campaign_id"], job["company"]))
        if company:
            dossier = attach_company_dossier(dossier, company)
        return self.save_research_dossier(batch_id, dossier)

    def record_company_dossier(self, batch_id: str, job_id: str, discovery_id: str,
                               capture_id: str, identity_quote: str, business_quote: str) -> dict[str, Any]:
        selected = {job["job_id"]: job for job in self.selected_jobs(batch_id)}
        if job_id not in selected:
            raise DomainError("G1 selection required before company research")
        job = selected[job_id]
        batch = self.store.get("batches", batch_id)
        discovery = self.store.get("discoveries", discovery_id)
        if (discovery is None or discovery.get("purpose") != "COMPANY_RESEARCH"
                or discovery.get("company") != job["company"]
                or discovery["campaign_id"] != batch["campaign_id"]
                or discovery["campaign_revision"] != batch["campaign_revision"]):
            raise ResearchError("company source does not match the selected Campaign and company")
        capture = next((item for item in discovery["captures"] if item["capture_id"] == capture_id), None)
        if capture is None or capture["content_state"] != "FETCHED_TEXT" or capture["source_url"] == job["source_url"]:
            raise ResearchError("independent readable company source required")
        body = capture["content_text"]
        if (not isinstance(identity_quote, str) or not isinstance(business_quote, str)
                or job["company"].casefold() not in identity_quote.casefold()
                or identity_quote not in body or business_quote not in body
                or len(business_quote.strip()) < 20):
            raise ResearchError("company identity and business quotes must occur exactly in the independent capture")
        key = self._company_record_key(batch["campaign_id"], job["company"])
        current = self.store.get("company_dossiers", key)
        if (current and current["capture_id"] == capture_id
                and current["identity_quote"] == identity_quote
                and current["business_quote"] == business_quote):
            return current
        value = {"schema": "company-dossier@1", "company_dossier_id": key,
                 "revision": current["revision"] + 1 if current else 1,
                 "campaign_id": batch["campaign_id"], "campaign_revision": batch["campaign_revision"],
                 "company": job["company"], "source_discovery_id": discovery_id,
                 "source_discovery_revision": discovery["revision"],
                 "capture_id": capture_id, "source_url": capture["source_url"],
                 "source_content_sha256": capture["raw_result_sha256"],
                 "captured_at": capture["captured_at"],
                 "identity_quote": identity_quote, "business_quote": business_quote,
                 "source_authority": "NOT_ASSESSED",
                 "created_at": current["created_at"] if current else utc_now(),
                 "updated_at": utc_now()}
        if current:
            return self.store.replace("company_dossiers", key, value, expected_revision=current["revision"])
        return self.store.put_new("company_dossiers", key, value)

    def refresh_research_with_company(self, batch_id: str, job_id: str) -> dict[str, Any] | None:
        selected = {job["job_id"]: job for job in self.selected_jobs(batch_id)}
        if job_id not in selected:
            raise DomainError("G1 selection required before company research reuse")
        job = selected[job_id]
        batch = self.store.get("batches", batch_id)
        company = self.store.get("company_dossiers", self._company_record_key(batch["campaign_id"], job["company"]))
        if company is None:
            raise ResearchError("no same-company public-source dossier exists")
        current = self.store.get("research", self._job_record_key(batch_id, job_id))
        if current is None:
            return None
        if (current.get("company_dossier_id") == company["company_dossier_id"]
                and current.get("company_dossier_revision") == company["revision"]):
            return current
        return self.save_research_dossier(batch_id, attach_company_dossier(current, company))

    def save_research_dossier(self, batch_id: str, dossier: dict[str, Any]) -> dict[str, Any]:
        selected = {job["job_id"]: job for job in self.selected_jobs(batch_id)}
        job_id = dossier.get("job_id")
        if job_id not in selected:
            raise DomainError("G1 selection required for job-specific research")
        job = selected[job_id]
        jd = dict(dossier.get("jd") or {})
        if jd.get("completeness") == "FULL":
            body = jd.get("body")
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest() if isinstance(body, str) else None
            owner_jd = self.store.get("owner_jds", self._job_record_key(batch_id, job_id))
            owner_confirmed = bool(owner_jd and owner_jd["sha256"] == digest and owner_jd["batch_id"] == batch_id)
            source_confirmed = False
            source_discovery_id = jd.get("source_discovery_id")
            if source_discovery_id:
                trace = self.store.get("discoveries", source_discovery_id)
                batch = self.store.get("batches", batch_id)
                if trace and batch and trace["campaign_id"] == batch["campaign_id"] and trace["campaign_revision"] == batch["campaign_revision"]:
                    source_confirmed = any(cap["capture_id"] == jd.get("source_capture_id")
                                           and cap["content_state"] == "FETCHED_TEXT"
                                           and isinstance(body, str) and body in cap["content_text"]
                                           for cap in trace["captures"])
            if not (owner_confirmed or source_confirmed):
                raise ResearchError("FULL JD requires a matching DSH Fetch capture or Owner-confirmed text")
            jd["owner_confirmed"] = owner_confirmed
            if owner_confirmed:
                jd["owner_jd_revision"] = owner_jd["revision"]
        value = {**dossier, "jd": jd}
        review = validate_research_dossier(value, job)
        batch = self.store.get("batches", batch_id)
        for row in value["business_evidence"]:
            if row["status"] != "VERIFIED":
                continue
            source_url = row["source_url"]
            quote = row["source_quote"]
            grounded = any(
                trace["campaign_id"] == batch["campaign_id"]
                and trace["campaign_revision"] == batch["campaign_revision"]
                and any(cap["source_url"] == source_url and cap["content_state"] == "FETCHED_TEXT"
                        and quote in cap["content_text"] for cap in trace["captures"])
                for trace in self.store.list_records("discoveries")
            )
            if not grounded:
                raise ResearchError("VERIFIED company evidence quote is not grounded in a matching DSH Fetch capture")
        record_key = self._job_record_key(batch_id, job_id)
        current = self.store.get("research", record_key)
        selection = self.store.get("selections", batch_id)
        value.update({"revision": current["revision"] + 1 if current else 1,
                      "batch_id": batch_id, "campaign_id": selection["campaign_id"],
                      "campaign_revision": selection["campaign_revision"],
                      "selection_id": selection["selection_id"],
                      "status": review["status"], "evidence_catalog": review,
                      "created_at": current["created_at"] if current else utc_now(),
                      "updated_at": utc_now()})
        if current:
            return self.store.replace("research", record_key, value, expected_revision=current["revision"])
        return self.store.put_new("research", record_key, value)

    def _plan_context(self, batch_id: str, job_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        selected = {job["job_id"]: job for job in self.selected_jobs(batch_id)}
        if job_id not in selected:
            raise DomainError("G1 selection required before plan")
        selection = self.store.get("selections", batch_id)
        research = self.store.get("research", self._job_record_key(batch_id, job_id))
        if research is None or research["status"] != "READY_FOR_PLAN":
            raise DomainError("complete selected-job research required before plan")
        if research["selection_id"] != selection["selection_id"]:
            raise DomainError("research selection version is stale")
        campaign = self.store.get("campaigns", selection["campaign_id"])
        if campaign is None or campaign["revision"] != research["campaign_revision"]:
            raise DomainError("research campaign version is stale")
        if self.master_path is None or hashlib.sha256(self.master_path.read_bytes()).hexdigest() != campaign["master_sha256"]:
            raise DomainError("master changed after G0; confirm a new Campaign revision")
        return campaign, selected[job_id], research, selection

    def _current_plan_snapshot(self, campaign: dict[str, Any], job_id: str,
                               research: dict[str, Any]) -> dict[str, Any]:
        profile = campaign["resume_profile"]
        return {"campaign_id": campaign["campaign_id"], "campaign_revision": campaign["revision"],
                "job_id": job_id, "jd_revision": research["jd"]["revision"],
                "jd_sha256": research["jd"]["sha256"], "research_revision": research["revision"],
                "master_sha256": campaign["master_sha256"],
                "resume_profile_revision": profile["revision"],
                "project_inventory_revision": profile["project_inventory_revision"]}

    def save_tailoring_plan(self, batch_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        job_id = plan.get("job_ref", {}).get("job_id")
        campaign, job, research, selection = self._plan_context(batch_id, job_id)
        required_inventory = [item for item in campaign["project_inventory"]["projects"] if item["include_in_resume"]]
        catalog = {"business_evidence_refs": research["evidence_catalog"]["business_evidence_refs"],
                   "fde_map_refs": research["evidence_catalog"]["fde_map_refs"],
                   "owner_evidence_refs": [item["evidence_id"] for item in campaign["resume_profile"]["owner_evidence"]]}
        current_snapshot = self._current_plan_snapshot(campaign, job_id, research)
        validation = validate_tailoring_plan(plan, required_inventory, research["jd"], catalog, current_snapshot)
        plan_id = plan["plan_id"]
        current = self.store.get("plans", plan_id)
        other_plans = [item for item in self.store.list_records("plans")
                       if item["batch_id"] == batch_id and item["job_id"] == job_id
                       and item["plan_id"] != plan_id]
        if other_plans:
            raise DomainError("one selected job may have only one formal plan ID; revise the existing plan")
        if current:
            if current["batch_id"] != batch_id or current["job_id"] != job_id:
                raise DomainError("plan ID already belongs to another job")
            if plan["plan_revision"] == current["revision"] and validation["plan_content_sha256"] == current["validation"]["plan_content_sha256"]:
                return current
            if plan["plan_revision"] != current["revision"] + 1:
                raise DomainError("plan revision must increase by one")
        else:
            if plan["plan_revision"] != 1:
                raise DomainError("new plan revision must be 1")
        record = {"schema": "stored-tailoring-plan@1", "plan_id": plan_id,
                  "revision": plan["plan_revision"], "batch_id": batch_id,
                  "campaign_id": campaign["campaign_id"], "job_id": job_id,
                  "selection_id": selection["selection_id"], "plan": plan,
                  "validation": validation, "status": "READY_FOR_APPROVAL",
                  "created_at": current["created_at"] if current else utc_now(),
                  "updated_at": utc_now()}
        if current:
            return self.store.replace("plans", plan_id, record, expected_revision=current["revision"])
        return self.store.put_new("plans", plan_id, record)

    def _live_plan_binding(self, record: dict[str, Any]) -> dict[str, Any]:
        campaign, _, research, selection = self._plan_context(record["batch_id"], record["job_id"])
        if record["selection_id"] != selection["selection_id"]:
            raise DomainError("plan selection version is stale")
        validation = record["validation"]
        target = {"plan_id": record["plan_id"], "plan_revision": record["revision"],
                  "plan_content_sha256": validation["plan_content_sha256"],
                  "input_snapshot_sha256": validation["input_snapshot_sha256"],
                  **validation["input_snapshot"]}
        return check_plan_binding(target, record["plan"],
                                  self._current_plan_snapshot(campaign, record["job_id"], research))

    def export_plan_reviews(self, batch_id: str) -> tuple[Path, dict[str, Any]]:
        selected = {job["job_id"]: job for job in self.selected_jobs(batch_id)}
        batch = self.store.get("batches", batch_id)
        campaign = self.store.get("campaigns", batch["campaign_id"])
        records = [record for record in self.store.list_records("plans") if record["batch_id"] == batch_id]
        if not records:
            raise DomainError("no plans ready for G2 review")
        entries = []
        for record in records:
            if record["job_id"] not in selected or self._live_plan_binding(record)["status"] != "MATCH":
                raise DomainError(f"plan {record['plan_id']} is stale; prepare a new revision")
            research = self.store.get("research", self._job_record_key(batch_id, record["job_id"]))
            entries.append({"plan": record["plan"], "job": selected[record["job_id"]], "research": research})
        inventory = [item for item in campaign["project_inventory"]["projects"] if item["include_in_resume"]]
        data, snapshot = export_plan_workbook(campaign["campaign_id"], batch_id, entries, inventory)
        filename = f"resume_tailoring_plans_{campaign['campaign_id']}_{batch_id}_{snapshot['export_id']}.xlsx"
        path = self._write_artifact("plan_exports", filename, data)
        snapshot["artifact_path"] = str(path)
        snapshot["workbook_sha256"] = hashlib.sha256(data).hexdigest()
        self.store.put_new("plan_exports", snapshot["export_id"], snapshot)
        return path, snapshot

    def preview_plan_reviews(self, export_id: str, data: bytes) -> dict[str, Any]:
        snapshot = self.store.get("plan_exports", export_id)
        if snapshot is None:
            raise DomainError("plan review export not found")
        current_bindings: dict[str, dict[str, Any]] = {}
        for plan_id in snapshot["rows"]:
            record = self.store.get("plans", plan_id)
            if record is None:
                continue
            try:
                live = self._live_plan_binding(record)
            except (DomainError, PlanError):
                continue
            if live["status"] == "MATCH":
                current_bindings[plan_id] = {"plan_revision": record["revision"],
                                             "input_snapshot_sha256": record["validation"]["input_snapshot_sha256"],
                                             "plan_content_sha256": record["validation"]["plan_content_sha256"]}
        preview = import_plan_workbook(data, snapshot, current_bindings)
        preview["artifact_path"] = str(self._write_artifact("plan_imports", preview["preview_id"] + ".xlsx", data))
        return self.store.put_new("plan_previews", preview["preview_id"], preview)

    def confirm_plan_reviews(self, preview_id: str, *, actor_channel: str) -> dict[str, Any]:
        actor = self._owner(actor_channel)
        preview = self.store.get("plan_previews", preview_id)
        if preview is None:
            raise DomainError("plan review preview not found")
        applied: list[dict[str, Any]] = []
        conflicts = list(preview["conflicts"])
        for row in preview["valid_rows"]:
            decision = row["decision"]
            if decision == "PENDING":
                continue
            plan_id = row["plan_id"]
            record = self.store.get("plans", plan_id)
            if record is None or record["revision"] != row["plan_revision"]:
                conflicts.append({"plan_id": plan_id, "reason": "STALE_PLAN_OR_INPUT"})
                continue
            try:
                live = self._live_plan_binding(record)
            except (DomainError, PlanError):
                live = {"status": "STALE"}
            if live["status"] != "MATCH" or any(row[key] != record["validation"][key] for key in ("input_snapshot_sha256", "plan_content_sha256")):
                conflicts.append({"plan_id": plan_id, "reason": "STALE_PLAN_OR_INPUT"})
                continue
            if decision == "REQUEST_CHANGES" and not (row["owner_comment"] and row["owner_comment"].strip()):
                conflicts.append({"plan_id": plan_id, "reason": "CHANGE_REQUEST_NEEDS_COMMENT"})
                continue
            if decision == "APPROVE" and row["owner_comment"] and row["owner_comment"].strip():
                conflicts.append({"plan_id": plan_id, "reason": "APPROVAL_WITH_CHANGE_REQUEST"})
                continue
            current = self.store.get("plan_decisions", plan_id)
            if current and current["decision"] == "REQUEST_CHANGES" and decision == "APPROVE" and current["plan_revision"] == record["revision"]:
                conflicts.append({"plan_id": plan_id, "reason": "NEW_PLAN_REVISION_REQUIRED_AFTER_CHANGES"})
                continue
            if current and current["file_sha256"] == preview["file_sha256"] and current["decision"] == decision and current["plan_revision"] == record["revision"]:
                applied.append(current)
                continue
            value = {"schema": "owner-plan-decision@1", "decision_id": "PDEC-" + uuid.uuid4().hex[:20].upper(),
                     "revision": current["revision"] + 1 if current else 1,
                     "campaign_id": preview["campaign_id"], "batch_id": preview["batch_id"],
                     "plan_id": plan_id, "plan_revision": record["revision"],
                     "job_id": record["job_id"], "input_snapshot_sha256": row["input_snapshot_sha256"],
                     "plan_content_sha256": row["plan_content_sha256"],
                     "decision": decision, "owner_comment": row["owner_comment"],
                     "owner_priority": row["owner_priority"], "export_id": preview["export_id"],
                     "preview_id": preview_id, "file_sha256": preview["file_sha256"],
                     "confirmed_by": actor, "confirmed_at": utc_now()}
            if current:
                value = self.store.replace("plan_decisions", plan_id, value, expected_revision=current["revision"])
            else:
                value = self.store.put_new("plan_decisions", plan_id, value)
            self.store.put_new("plan_decision_events", value["decision_id"], value)
            applied.append(value)
        return {"schema": "plan-review-confirmation@1", "preview_id": preview_id,
                "applied": applied, "conflicts": conflicts}

    def authorized_plan(self, plan_id: str) -> dict[str, Any]:
        decision = self.store.get("plan_decisions", plan_id)
        if decision is None or decision["decision"] != "APPROVE":
            raise DomainError("G2 approval required before resume generation")
        record = self.store.get("plans", plan_id)
        if record is None or decision["plan_revision"] != record["revision"]:
            raise DomainError("approved plan revision is stale")
        if any(decision[key] != record["validation"][key] for key in ("input_snapshot_sha256", "plan_content_sha256")):
            raise DomainError("approved plan/input hash is stale")
        if self._live_plan_binding(record)["status"] != "MATCH":
            raise DomainError("approved plan inputs changed; new G2 review required")
        return {"plan": record["plan"], "decision": decision,
                "validation": record["validation"]}

    def generate_resume_candidate(self, plan_id: str) -> dict[str, Any]:
        """Render one G2-approved version; QA failure stays a candidate conflict."""
        authorization = self.authorized_plan(plan_id)
        plan = authorization["plan"]
        validation = authorization["validation"]
        if any(item["plan_id"] == plan_id and item["plan_revision"] == plan["plan_revision"]
               and item["status"] == "OWNER_REQUESTED_CHANGES"
               for item in self.store.list_records("resume_artifacts")):
            raise DomainError("Owner requested changes to this PDF; revise plan and obtain new G2 approval")
        campaign = self.store.get("campaigns", plan["campaign_id"])
        self._require_current_master(campaign)
        master_bytes = self.master_path.read_bytes()
        content = build_resume_content(master_bytes, campaign, plan)
        markup = content_html(content, plan)
        artifact_id = "RES-" + uuid.uuid4().hex[:20].upper()
        target_dir = self.artifacts / "resumes"
        target_dir.mkdir(parents=True, exist_ok=True)
        html_path = self._write_artifact("resumes", artifact_id + ".html", markup.encode("utf-8"))
        pdf_path = target_dir / (artifact_id + ".pdf")
        expected = [content["name"], *[row["name"] for row in content["projects"]],
                    *[row["text"] for row in content["highlights"]]]
        qa = render_and_inspect(html_path, pdf_path, expected_project_ids=content["project_ids"],
                                expected_text=expected)
        # A long render cannot inherit approval if any input changes meanwhile.
        fresh = self.authorized_plan(plan_id)
        if fresh["decision"]["decision_id"] != authorization["decision"]["decision_id"]:
            raise DomainError("G2 decision changed during rendering; discard this candidate")
        value = {"schema": "resume-candidate-artifact@1", "artifact_id": artifact_id,
                 "revision": 1, "status": qa["status"], "plan_id": plan_id,
                 "plan_revision": plan["plan_revision"],
                 "plan_content_sha256": validation["plan_content_sha256"],
                 "input_snapshot_sha256": validation["input_snapshot_sha256"],
                 "approval_decision_id": authorization["decision"]["decision_id"],
                 "campaign_id": campaign["campaign_id"], "job_id": plan["job_ref"]["job_id"],
                 "master_sha256": campaign["master_sha256"],
                 "content_sha256": hashlib.sha256(markup.encode("utf-8")).hexdigest(),
                 "pdf_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
                 "content_path": str(html_path), "pdf_path": str(pdf_path),
                 "content_project_ids": content["project_ids"], "qa": qa,
                 "created_at": utc_now(), "owner_review": None}
        return self.store.put_new("resume_artifacts", artifact_id, value)

    def review_resume_candidate(self, artifact_id: str, *, decision: str,
                                reviewed_pdf_sha256: str, visual_checks: dict[str, bool] | None,
                                owner_comment: str | None, actor_channel: str) -> dict[str, Any]:
        actor = self._owner(actor_channel)
        current = self.store.get("resume_artifacts", artifact_id)
        if current is None:
            raise DomainError("resume candidate artifact not found")
        if decision not in {"APPROVE", "REQUEST_CHANGES"}:
            raise DomainError("G3 decision must be APPROVE or REQUEST_CHANGES")
        if reviewed_pdf_sha256 != current["pdf_sha256"]:
            raise DomainError("G3 reviewed PDF hash differs from candidate")
        pdf_path = Path(current["pdf_path"])
        if not pdf_path.is_file() or hashlib.sha256(pdf_path.read_bytes()).hexdigest() != current["pdf_sha256"]:
            raise DomainError("G3 PDF file changed since QA")
        if current.get("owner_review"):
            review = current["owner_review"]
            if review["decision"] == decision and review["reviewed_pdf_sha256"] == reviewed_pdf_sha256:
                return current
            raise DomainError("G3 review already recorded for this artifact; generate a new candidate")
        if decision == "APPROVE":
            if current["status"] != "WAITING_VISUAL_REVIEW" or current["qa"]["problems"]:
                raise DomainError("G3 cannot approve a PDF that failed two-page/content QA")
            images = current["qa"].get("page_image_paths") or []
            image_hashes = current["qa"].get("page_image_sha256") or []
            if len(images) != 2 or len(image_hashes) != 2 or any(
                not Path(image).is_file() or hashlib.sha256(Path(image).read_bytes()).hexdigest() != digest
                for image, digest in zip(images, image_hashes)
            ):
                raise DomainError("G3 requires two unchanged rendered page images")
            with pdfplumber.open(pdf_path) as document:
                if len(document.pages) != 2 or any(abs(page.width - 595.28) >= 2 or abs(page.height - 841.89) >= 2
                                                   for page in document.pages):
                    raise DomainError("G3 PDF is not exactly two A4 pages")
            required_checks = {"both_pages_readable", "no_clipping_or_overlap", "all_projects_visible"}
            if not isinstance(visual_checks, dict) or set(visual_checks) != required_checks or any(
                visual_checks[key] is not True for key in required_checks
            ):
                raise DomainError("G3 approval requires all three explicit visual checks")
            live = self.authorized_plan(current["plan_id"])
            if live["decision"]["decision_id"] != current["approval_decision_id"]:
                raise DomainError("approved plan decision changed after PDF generation")
        elif not isinstance(owner_comment, str) or not owner_comment.strip():
            raise DomainError("G3 change request needs a concrete comment")
        review = {"schema": "owner-resume-review@1", "decision": decision,
                  "reviewed_pdf_sha256": reviewed_pdf_sha256,
                  "visual_checks": visual_checks if decision == "APPROVE" else None,
                  "owner_comment": owner_comment.strip() if isinstance(owner_comment, str) and owner_comment.strip() else None,
                  "reviewed_by": actor, "reviewed_at": utc_now()}
        revised = {**current, "revision": current["revision"] + 1,
                   "status": "OWNER_APPROVED" if decision == "APPROVE" else "OWNER_REQUESTED_CHANGES",
                   "owner_review": review, "updated_at": utc_now()}
        return self.store.replace("resume_artifacts", artifact_id, revised,
                                  expected_revision=current["revision"])

    def export_handoff(self, artifact_id: str) -> dict[str, Any]:
        artifact = self.store.get("resume_artifacts", artifact_id)
        if artifact is None or artifact["status"] != "OWNER_APPROVED" or not artifact.get("owner_review"):
            raise DomainError("G3 Owner-approved resume required before handoff")
        live = self.authorized_plan(artifact["plan_id"])
        if live["decision"]["decision_id"] != artifact["approval_decision_id"]:
            raise DomainError("handoff PDF no longer matches the approved plan decision")
        if hashlib.sha256(Path(artifact["pdf_path"]).read_bytes()).hexdigest() != artifact["pdf_sha256"]:
            raise DomainError("handoff PDF file hash differs from G3 reviewed artifact")
        prior = next((item for item in self.store.list_records("handoffs")
                      if item["artifact_id"] == artifact_id and item["pdf_sha256"] == artifact["pdf_sha256"]), None)
        if prior:
            return prior
        plan_record = self.store.get("plans", artifact["plan_id"])
        batch = self.store.get("batches", plan_record["batch_id"])
        job = batch["jobs"][artifact["job_id"]]
        research = self.store.get("research", self._job_record_key(plan_record["batch_id"], artifact["job_id"]))
        if research is None or research["status"] != "READY_FOR_PLAN":
            raise DomainError("selected-job research is missing for handoff")
        with pdfplumber.open(artifact["pdf_path"]) as document:
            readable = "\n\n".join(page.extract_text() or "" for page in document.pages)
        if not readable.strip():
            raise DomainError("approved PDF has no extractable text for handoff")
        job_card = {key: job.get(key) for key in (
            "job_id", "company", "title", "city", "source_url", "source_platform",
            "salary_raw", "opening_status", "captured_at", "risk_flags")}
        application_card = research["application_card"]
        prompt = (
            "请基于随包的完整 JD、公司研究和岗位卡准备面试研究。区分 VERIFIED、INFERRED、OWNER_PROVIDED 与 NOT_FOUND；"
            "逐项给出来源 URL、引用片段和抓取时间。不要把岗位页当成已核实投递入口，不要捏造公司内部流程或个人经历。"
            "输出岗位业务理解、可能问题、我的项目证据映射、待核实清单；这是外部研究输入，不能将交接包就绪视作研究完成。"
        )
        manifest = {"schema": "career-handoff@1", "status": "HANDOFF_READY",
                    "artifact_id": artifact_id, "pdf_sha256": artifact["pdf_sha256"],
                    "plan_id": artifact["plan_id"], "plan_revision": artifact["plan_revision"],
                    "input_snapshot_sha256": artifact["input_snapshot_sha256"],
                    "job_id": artifact["job_id"], "application_status": application_card["application_status"],
                    "interview_research_status": "NOT_STARTED"}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr("job_card.json", json.dumps(job_card, ensure_ascii=False, indent=2))
            archive.writestr("application_card.json", json.dumps(application_card, ensure_ascii=False, indent=2))
            archive.writestr("research.json", json.dumps(research, ensure_ascii=False, indent=2))
            archive.writestr("full_jd.txt", research["jd"]["body"])
            archive.writestr("resume.pdf", Path(artifact["pdf_path"]).read_bytes())
            archive.writestr("resume_readable.txt", readable)
            archive.writestr("interview_research_prompt.txt", prompt)
        handoff_id = "HND-" + uuid.uuid4().hex[:20].upper()
        path = self._write_artifact("handoffs", handoff_id + ".zip", stream.getvalue())
        record = {**manifest, "handoff_id": handoff_id, "revision": 1,
                  "zip_sha256": hashlib.sha256(stream.getvalue()).hexdigest(),
                  "zip_path": str(path), "created_at": utc_now()}
        return self.store.put_new("handoffs", handoff_id, record)

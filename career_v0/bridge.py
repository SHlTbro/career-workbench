"""Small JSON stdin bridge for the authenticated DSH Career Host plugin.

The browser never supplies actor_channel. The Host injects a per-process secret
only after an authenticated explicit action route. No model tool may call this
bridge with a fabricated OWNER_UI string and thereby grant itself approval.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

from .service import CareerService


class BridgeError(ValueError):
    pass


def _upload_bytes(state_dir: Path, path_value: Any) -> bytes:
    if not isinstance(path_value, str):
        raise BridgeError("upload path missing")
    path = Path(path_value).resolve()
    upload_root = (state_dir / "_uploads").resolve()
    if upload_root not in path.parents or not path.is_file():
        raise BridgeError("upload must be a Host-owned temporary file")
    if path.stat().st_size > 10 * 1024 * 1024:
        raise BridgeError("upload larger than 10 MB")
    return path.read_bytes()


def _source_summary(item: dict[str, Any]) -> dict[str, Any]:
    """Keep full captured pages in Host storage, not Web list responses."""
    summary = {key: item.get(key) for key in (
        "discovery_id", "revision", "campaign_id", "campaign_revision",
        "purpose", "company", "created_at", "leads",
    )}
    summary["captures"] = [{key: capture.get(key) for key in (
        "capture_id", "source_url", "http_status", "content_state", "captured_at",
    )} for capture in item["captures"]]
    return summary


def run(request: dict[str, Any], *, state_dir: Path, master_path: Path,
        owner_secret: str | None) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise BridgeError("request must be a JSON object")
    service = CareerService(state_dir, master_path=master_path,
                            owner_action_verifier=(lambda proof: secrets.compare_digest(proof, owner_secret)) if owner_secret else None)
    op = request.get("op")
    if op == "inventory_candidate":
        return service.inventory_candidate()
    if op == "list_campaigns":
        return {"campaigns": service.store.list_records("campaigns")}
    if op == "get_campaign":
        return {"campaign": service.store.get("campaigns", request["campaign_id"])}
    if op == "create_campaign":
        return {"campaign": service.create_campaign(request["preferences"])}
    if op == "list_batches":
        return {"batches": [item for item in service.store.list_records("batches") if item["campaign_id"] == request["campaign_id"]]}
    if op == "search_sources":
        from .discovery_runner import run_search
        return {"search": run_search(service, request["campaign_id"])}
    if op == "fetch_source":
        from .discovery_runner import run_fetch
        return {"fetch": run_fetch(service, request["discovery_id"], request["source_url"])}
    if op == "normalize_source":
        from .discovery_runner import normalize_capture
        return {"normalized": normalize_capture(service, request["discovery_id"], request["capture_id"])}
    if op == "list_normalized_sources":
        return {"normalized": [item for item in service.store.list_records("normalized_jobs")
                               if item["discovery_id"] == request["discovery_id"]]}
    if op == "create_batch_from_normalizations":
        return {"batch": service.create_batch_from_normalizations(request["discovery_id"], request["normalized_ids"])}
    if op == "list_discoveries":
        return {"discoveries": [_source_summary(item) for item in service.store.list_records("discoveries")
                                if item["campaign_id"] == request["campaign_id"]
                                and item.get("purpose", "JOB_SOURCES") == "JOB_SOURCES"]}
    if op == "get_batch":
        return {"batch": service.store.get("batches", request["batch_id"])}
    if op == "list_candidate_exports":
        return {"exports": [item for item in service.store.list_records("exports")
                            if item["batch_id"] == request["batch_id"]]}
    if op == "list_selection_previews":
        return {"previews": [item for item in service.store.list_records("previews")
                             if item["batch_id"] == request["batch_id"]]}
    if op == "get_selection":
        return {"selection": service.store.get("selections", request["batch_id"])}
    if op == "selected_jobs":
        return {"jobs": service.selected_jobs(request["batch_id"])}
    if op == "search_company_sources":
        from .company_runner import search_company_sources
        return {"search": search_company_sources(service, request["batch_id"], request["job_id"])}
    if op == "list_company_sources":
        selection = service.store.get("selections", request["batch_id"])
        companies = {job["company"] for job in service.selected_jobs(request["batch_id"])}
        return {"sources": [_source_summary(item) for item in service.store.list_records("discoveries")
                            if item.get("purpose") == "COMPANY_RESEARCH"
                            and item["campaign_id"] == selection["campaign_id"]
                            and item["company"] in companies]}
    if op == "prepare_company_dossier":
        from .company_runner import prepare_company_dossier
        return prepare_company_dossier(service, request["batch_id"], request["job_id"],
                                       request["discovery_id"], request["capture_id"])
    if op == "list_company_dossiers":
        selection = service.store.get("selections", request["batch_id"])
        companies = {job["company"] for job in service.selected_jobs(request["batch_id"])}
        return {"dossiers": [item for item in service.store.list_records("company_dossiers")
                             if item["campaign_id"] == selection["campaign_id"]
                             and item["company"] in companies]}
    if op == "prepare_selected_research":
        return {"research": service.prepare_selected_source_research(request["batch_id"], request["job_id"])}
    if op == "list_research":
        return {"research": [item for item in service.store.list_records("research")
                             if item["batch_id"] == request["batch_id"]]}
    if op == "prepare_tailoring_plan":
        from .planning_runner import prepare_tailoring_plan
        return {"plan": prepare_tailoring_plan(service, request["batch_id"], request["job_id"])}
    if op == "list_plans":
        return {"plans": [item for item in service.store.list_records("plans")
                          if item["batch_id"] == request["batch_id"]]}
    if op == "list_plan_exports":
        return {"exports": [item for item in service.store.list_records("plan_exports")
                            if item["batch_id"] == request["batch_id"]]}
    if op == "list_plan_previews":
        return {"previews": [item for item in service.store.list_records("plan_previews")
                             if item["batch_id"] == request["batch_id"]]}
    if op == "list_plan_decisions":
        return {"decisions": [item for item in service.store.list_records("plan_decisions")
                              if item["batch_id"] == request["batch_id"]]}
    if op == "list_resume_artifacts":
        plan_ids = {item["plan_id"] for item in service.store.list_records("plans")
                    if item["batch_id"] == request["batch_id"]}
        return {"artifacts": [item for item in service.store.list_records("resume_artifacts")
                              if item["plan_id"] in plan_ids]}
    if op == "get_resume_artifact":
        return {"artifact": service.store.get("resume_artifacts", request["artifact_id"])}
    if op == "generate_resume_candidate":
        return {"artifact": service.generate_resume_candidate(request["plan_id"])}
    if op == "review_resume_candidate":
        return {"artifact": service.review_resume_candidate(
            request["artifact_id"], decision=request["decision"],
            reviewed_pdf_sha256=request["reviewed_pdf_sha256"],
            visual_checks=request.get("visual_checks"), owner_comment=request.get("owner_comment"),
            actor_channel="OWNER_UI:" + (owner_secret or ""))}
    if op == "export_handoff":
        return {"handoff": service.export_handoff(request["artifact_id"])}
    if op == "list_handoffs":
        return {"handoffs": [item for item in service.store.list_records("handoffs")
                             if item["artifact_id"] == request["artifact_id"]]}
    if op == "get_handoff":
        return {"handoff": service.store.get("handoffs", request["handoff_id"])}
    if op == "confirm_campaign":
        return {"campaign": service.confirm_campaign(request["campaign_id"], actor_channel="OWNER_UI:" + (owner_secret or ""))}
    if op == "revise_campaign":
        return {"campaign": service.revise_campaign(request["campaign_id"], request["preferences"],
                                                     actor_channel="OWNER_UI:" + (owner_secret or ""))}
    if op == "export_candidates":
        path, snapshot = service.export_candidates(request["batch_id"])
        return {"artifact_path": str(path), "snapshot": snapshot}
    if op == "preview_selection":
        data = _upload_bytes(state_dir, request.get("upload_path"))
        return {"preview": service.preview_selection(request["export_id"], data)}
    if op == "confirm_selection":
        return {"selection": service.confirm_selection(request["preview_id"],
                                                       actor_channel="OWNER_UI:" + (owner_secret or ""),
                                                       accept_shortfall=request.get("accept_shortfall") is True)}
    if op == "export_plan_reviews":
        path, snapshot = service.export_plan_reviews(request["batch_id"])
        return {"artifact_path": str(path), "snapshot": snapshot}
    if op == "preview_plan_reviews":
        data = _upload_bytes(state_dir, request.get("upload_path"))
        return {"preview": service.preview_plan_reviews(request["export_id"], data)}
    if op == "confirm_plan_reviews":
        return {"result": service.confirm_plan_reviews(request["preview_id"],
                                                       actor_channel="OWNER_UI:" + (owner_secret or ""))}
    if op == "confirm_owner_jd":
        return {"owner_jd": service.confirm_owner_jd(request["batch_id"], request["job_id"], request["body"],
                                                     actor_channel="OWNER_UI:" + (owner_secret or ""))}
    raise BridgeError("unsupported Career bridge operation")


def main() -> int:
    state = Path(os.environ.get("CAREER_STATE_DIR", "")).resolve()
    master = Path(os.environ.get("CAREER_MASTER_PATH", "")).resolve()
    secret = os.environ.get("CAREER_OWNER_ACTION_SECRET")
    if not os.environ.get("CAREER_STATE_DIR") or not os.environ.get("CAREER_MASTER_PATH"):
        print(json.dumps({"ok": False, "error": "Career Host state/master paths not configured"}), flush=True)
        return 2
    try:
        request = json.loads(sys.stdin.read())
        result = run(request, state_dir=state, master_path=master, owner_secret=secret)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, separators=(",", ":")), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__},
                         ensure_ascii=False, separators=(",", ":")), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Selected-job research and application-card rules for V-0."""

from __future__ import annotations

import hashlib
import copy
from typing import Any
from urllib.parse import urlsplit

from .discovery import _quoted_section, _markdown_relaxed_hit


class ResearchError(ValueError):
    pass


CARD_FIELDS = (
    "job_id", "company", "title", "source_url", "source_platform",
    "original_publisher", "apply_method", "apply_url", "application_status",
    "login_required", "deadline", "opening_status", "contact_person",
    "contact_email", "contact_scope", "required_materials",
    "recommended_resume_ref", "last_verified_at", "evidence_refs", "next_action",
    "unknown_reasons",
)
CARD_STATES = {"READY_TO_APPLY", "NEEDS_LOGIN", "NEEDS_ORIGINAL_CHANNEL", "NEEDS_OWNER_ACTION", "NOT_FOUND", "CLOSED"}
FDE_FIELDS = ("business_scenario", "users_and_team", "workflow", "pain_hypothesis",
              "ai_entry_point", "engineering_constraints", "jd_capability", "owner_project_evidence", "tailoring_action")


def selected_source_dossier(job: dict[str, Any], capture: dict[str, Any],
                            discovery_id: str) -> dict[str, Any]:
    """Create a traceable JD-first dossier with explicit company/channel gaps.

    It uses the G0 candidate's exact JD spans. Independent company research can
    replace this later; the role page alone is never presented as proof of a
    company-wide business line or an application channel.
    """
    if job.get("jd_completeness") != "FULL" or capture.get("content_state") != "FETCHED_TEXT":
        raise ResearchError("FULL selected-job JD capture required")
    if capture.get("capture_id") != job.get("source_capture_id") or capture.get("source_url") != job.get("source_url"):
        raise ResearchError("selected job and JD capture identity differ")
    sections = job.get("jd_sections") or {}
    body = capture.get("content_text")

    def _section_lines(value: Any) -> list[str] | None:
        """A quoted section is one verbatim span of the capture (markdown emphasis
        tolerated), or a list whose every line is verbatim in it. Returns the
        lines to display, else None."""
        if isinstance(value, str):
            return [value] if len(value) >= 10 and _quoted_section(value, body or "") else None
        if isinstance(value, list) and value and _quoted_section(value, body or ""):
            return [item for item in value if isinstance(item, str)]
        return None

    responsibility_lines = _section_lines(sections.get("responsibilities"))
    requirement_lines = _section_lines(sections.get("requirements"))
    if not body or not responsibility_lines or not requirement_lines:
        raise ResearchError("selected job JD quotes do not occur in the captured body")
    responsibility = "\n".join(responsibility_lines)
    requirement = "\n".join(requirement_lines)
    unknown_fields = ("original_publisher", "apply_method", "apply_url", "login_required",
                      "deadline", "contact_person", "contact_email", "contact_scope",
                      "recommended_resume_ref", "last_verified_at")
    unknown_reasons = {field: "职位页没有可核验的该字段；需到官方投递渠道核实" for field in unknown_fields}
    if job.get("opening_status") is None:
        unknown_reasons["opening_status"] = "未找到当前开放状态的可核验证据"
    card = {
        "job_id": job["job_id"], "company": job["company"], "title": job["title"],
        "source_url": job["source_url"], "source_platform": job["source_platform"],
        "original_publisher": None, "apply_method": None, "apply_url": None,
        "application_status": "NEEDS_ORIGINAL_CHANNEL", "login_required": None,
        "deadline": None, "opening_status": job.get("opening_status"),
        "contact_person": None, "contact_email": None, "contact_scope": None,
        "required_materials": [], "recommended_resume_ref": None,
        "last_verified_at": None, "evidence_refs": [],
        "next_action": "Owner 核实官方投递入口、当前开放状态和所需材料",
        "unknown_reasons": unknown_reasons,
    }
    requirement_ids = [f"JD-R{i}" for i in range(1, len(requirement_lines) + 1)]
    requirement_quotes = dict(zip(requirement_ids, requirement_lines))
    return {
        "schema": "research-dossier@1", "job_id": job["job_id"],
        "company": job["company"],
        "business_summary": "当前仅核实职位 JD 所述工作范围；公司业务线尚未独立核实。",
        "business_scope_status": "ROLE_JD_ONLY",
        "jd": {"job_id": job["job_id"], "revision": 1, "body": body,
               "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
               "completeness": "FULL", "source_url": job["source_url"],
               "source_discovery_id": discovery_id,
               "source_capture_id": capture["capture_id"],
               "requirement_ids": requirement_ids,
               "requirement_quotes": requirement_quotes},
        "business_evidence": [{"evidence_id": f"COMPANY-ROLE-JD-{i}", "status": "VERIFIED",
                               "scope": "ROLE_JD_ONLY", "source_url": job["source_url"],
                               "source_quote": line}
                              for i, line in enumerate(responsibility_lines, start=1)],
        "fde_map": [{"fde_id": "FDE-ROLE-1", "status": "INFERRED",
                     "reasoning": "仅基于公开 JD 的职责和要求构造准备视角，不能当作公司内部事实",
                     "business_scenario": "职位 JD 所述工作范围；公司业务线待核实",
                     "users_and_team": "未在职位页核实",
                     "workflow": responsibility,
                     "pain_hypothesis": "待公司研究或面试验证",
                     "ai_entry_point": "依职位 JD 的工程职责判断，尚非公司项目事实",
                     "engineering_constraints": requirement,
                     "jd_capability": requirement,
                     "owner_project_evidence": "待逐项目方案引用 Owner 确认证据",
                     "tailoring_action": "只用 Owner 已确认项目与 JD 能力作对应，不新增行业经历"}],
        "application_card": card,
        "unknowns": ["公司业务线未独立核实", "官方投递渠道未核实", "FDE 痛点只是准备假设"],
    }


def attach_company_dossier(dossier: dict[str, Any], company: dict[str, Any]) -> dict[str, Any]:
    """Reuse one independent public source without mixing job-specific JD facts."""
    if dossier.get("company") != company.get("company") or dossier.get("campaign_id", company.get("campaign_id")) != company.get("campaign_id"):
        raise ResearchError("company dossier identity differs from selected job research")
    revised = copy.deepcopy(dossier)
    revised["company_dossier_id"] = company["company_dossier_id"]
    revised["company_dossier_revision"] = company["revision"]
    revised["business_summary"] = "公司公开来源摘录：" + company["business_quote"]
    revised["business_scope_status"] = "PUBLIC_SOURCE_QUOTE_AUTHORITY_UNVERIFIED"
    revised["business_evidence"] = [row for row in revised["business_evidence"]
                                    if row.get("scope") != "PUBLIC_COMPANY_SOURCE"]
    revised["business_evidence"].append({
        "evidence_id": "COMPANY-PUBLIC-" + company["company_dossier_id"],
        "status": "VERIFIED", "scope": "PUBLIC_COMPANY_SOURCE",
        "source_url": company["source_url"], "source_quote": company["business_quote"],
        "captured_at": company["captured_at"], "source_authority": "NOT_ASSESSED",
    })
    revised["unknowns"] = [item for item in revised["unknowns"]
                            if item != "公司业务线未独立核实"]
    if "公开来源权威性与时效未核实" not in revised["unknowns"]:
        revised["unknowns"].append("公开来源权威性与时效未核实")
    return revised


def _url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parts = urlsplit(value)
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def validate_application_card(card: dict[str, Any], job: dict[str, Any]) -> None:
    if not isinstance(card, dict) or any(field not in card for field in CARD_FIELDS):
        raise ResearchError("Application Card must include every required field, including explicit unknowns")
    for field in ("job_id", "company", "title"):
        if card[field] != job.get(field):
            raise ResearchError(f"Application Card {field} differs from selected job")
    if not _url(card["source_url"]):
        raise ResearchError("Application Card source_url missing")
    permitted_sources = {job.get("source_url"), *(ref.get("source_url") for ref in job.get("source_refs", []) if isinstance(ref, dict))}
    if card["source_url"] not in permitted_sources:
        raise ResearchError("Application Card source_url is unrelated to the selected job")
    if card["apply_url"] is not None and not _url(card["apply_url"]):
        raise ResearchError("Application Card apply_url invalid")
    if card["application_status"] not in CARD_STATES:
        raise ResearchError("Application Card status invalid")
    if type(card["login_required"]) is not bool and card["login_required"] is not None:
        raise ResearchError("login_required must be boolean or unknown")
    if not isinstance(card["evidence_refs"], list) or not isinstance(card["unknown_reasons"], dict):
        raise ResearchError("Application Card evidence/unknown reasons missing")
    for field in ("original_publisher", "apply_method", "apply_url", "login_required",
                  "deadline", "opening_status", "contact_person", "contact_email",
                  "contact_scope", "recommended_resume_ref", "last_verified_at"):
        if card[field] is None and not card["unknown_reasons"].get(field):
            raise ResearchError(f"Application Card {field} needs an explicit unknown reason")
    if card["contact_scope"] == "ROLE_SPECIFIC" and (not card["contact_email"] or not card["evidence_refs"]):
        raise ResearchError("role-specific contact needs a verified address and evidence")
    if card["application_status"] == "READY_TO_APPLY":
        if card["opening_status"] != "OPEN" or card["login_required"] is not False:
            raise ResearchError("READY_TO_APPLY requires verified open, no-login channel")
        if not card["apply_method"] or not (card["apply_url"] or card["contact_email"]):
            raise ResearchError("READY_TO_APPLY requires a concrete application channel")
        if not card["last_verified_at"] or not card["evidence_refs"]:
            raise ResearchError("READY_TO_APPLY requires fresh channel evidence")
    if card["opening_status"] == "CLOSED" and card["application_status"] != "CLOSED":
        raise ResearchError("closed posting cannot show an active application state")


def validate_research_dossier(dossier: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    if dossier.get("schema") != "research-dossier@1":
        raise ResearchError("research dossier schema invalid")
    if dossier.get("job_id") != job["job_id"] or dossier.get("company") != job["company"]:
        raise ResearchError("research dossier crosses selected job/company identity")
    jd = dossier.get("jd")
    if not isinstance(jd, dict) or jd.get("job_id") != job["job_id"]:
        raise ResearchError("job-specific JD missing")
    body = jd.get("body")
    if body is not None and not isinstance(body, str):
        raise ResearchError("JD body must be text or null")
    if body and hashlib.sha256(body.encode("utf-8")).hexdigest() != jd.get("sha256"):
        raise ResearchError("JD body hash mismatch")
    if jd.get("completeness") == "FULL":
        if not body or not jd.get("requirement_ids") or not isinstance(jd["requirement_ids"], list):
            raise ResearchError("FULL JD requires body and requirement IDs")
        quotes = jd.get("requirement_quotes")
        if (not isinstance(quotes, dict) or set(quotes) != set(jd["requirement_ids"])
                or any(not isinstance(quote, str) or len(quote.strip()) < 10
                       or not _markdown_relaxed_hit(quote, body)
                       for quote in quotes.values())):
            raise ResearchError("FULL JD requirement IDs need exact body quotes")
        if not (_url(jd.get("source_url")) or jd.get("owner_confirmed") is True):
            raise ResearchError("FULL JD requires source URL or Owner-confirmed text")
    elif jd.get("completeness") not in {"PARTIAL", "TITLE_ONLY"}:
        raise ResearchError("JD completeness invalid")
    evidence = dossier.get("business_evidence")
    if not isinstance(evidence, list):
        raise ResearchError("company business evidence list missing")
    evidence_ids: set[str] = set()
    for row in evidence:
        if not isinstance(row, dict) or not row.get("evidence_id") or row["evidence_id"] in evidence_ids:
            raise ResearchError("company evidence ID missing or duplicated")
        evidence_ids.add(row["evidence_id"])
        if row.get("status") not in {"VERIFIED", "INFERRED", "OWNER_PROVIDED", "NOT_FOUND"}:
            raise ResearchError("company evidence status invalid")
        if row["status"] == "VERIFIED" and (not _url(row.get("source_url")) or not row.get("source_quote")):
            raise ResearchError("VERIFIED business evidence needs URL and quote")
        if row["status"] == "INFERRED" and not row.get("reasoning"):
            raise ResearchError("INFERRED business statement needs reasoning")
    fde = dossier.get("fde_map")
    if not isinstance(fde, list):
        raise ResearchError("FDE map missing")
    fde_ids: set[str] = set()
    for row in fde:
        if not isinstance(row, dict) or not row.get("fde_id") or row["fde_id"] in fde_ids:
            raise ResearchError("FDE map ID missing or duplicated")
        fde_ids.add(row["fde_id"])
        if any(field not in row for field in FDE_FIELDS):
            raise ResearchError("FDE map must cover business-to-action chain")
        if row.get("status") not in {"VERIFIED", "INFERRED", "OWNER_PROVIDED", "NOT_FOUND"}:
            raise ResearchError("FDE map status invalid")
    validate_application_card(dossier.get("application_card"), job)
    if not isinstance(dossier.get("unknowns"), list):
        raise ResearchError("dossier unknowns list missing")
    return {"status": "READY_FOR_PLAN" if jd["completeness"] == "FULL" else "RESEARCH_BLOCKED",
            "business_evidence_refs": sorted(evidence_ids), "fde_map_refs": sorted(fde_ids),
            "jd_requirement_refs": jd.get("requirement_ids") or []}

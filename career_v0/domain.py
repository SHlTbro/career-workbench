"""Stable Career campaign and candidate-pool rules for the V-0 journey."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any


class DomainError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_campaign_preferences(preferences: dict[str, Any]) -> None:
    """G0 accepts an explicit preference choice, including explicit ANY choices."""
    if preferences.get("recruitment_type") != "AUTUMN_CAMPUS":
        raise DomainError("V-0 campaign requires confirmed AUTUMN_CAMPUS recruitment type")
    if preferences.get("allow_internships") is not False:
        raise DomainError("internships cannot be silently enabled for this campaign")
    if preferences.get("graduation_year") != 2027:
        raise DomainError("graduation_year must be confirmed as 2027")
    roles = preferences.get("target_roles")
    if not isinstance(roles, list) or not roles or not all(isinstance(x, str) and x.strip() for x in roles) or len({x.strip().casefold() for x in roles}) != len(roles):
        raise DomainError("target_roles must be a confirmed nonempty list")
    city = preferences.get("city_scope")
    if not isinstance(city, dict) or city.get("mode") not in {"ANY", "CITIES", "REMOTE"}:
        raise DomainError("city_scope must be explicitly confirmed")
    if city["mode"] == "CITIES" and (not isinstance(city.get("values"), list) or not city["values"] or not all(isinstance(value, str) and value.strip() for value in city["values"])):
        raise DomainError("CITIES requires at least one named city")
    if preferences.get("company_scope") not in {"ANY", "FILTERED"}:
        raise DomainError("company_scope must be explicitly confirmed")
    if preferences["company_scope"] == "FILTERED":
        filters = preferences.get("company_filters")
        if not isinstance(filters, dict) or not any(filters.get(k) for k in ("names", "sizes")):
            raise DomainError("FILTERED company_scope requires confirmed names or sizes")
        for key in ("names", "sizes"):
            values = filters.get(key, [])
            if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
                raise DomainError(f"company filter {key} must be a list of nonempty names")
    adjacent = preferences.get("adjacent_role_policy")
    if not isinstance(adjacent, dict) or any(type(adjacent.get(k)) is not bool for k in ("frontend", "algorithm", "sales")):
        raise DomainError("frontend/algorithm/sales preferences must be explicitly confirmed")
    salary = preferences.get("salary")
    if not isinstance(salary, dict):
        raise DomainError("salary must be confirmed")
    if salary.get("currency") != "CNY" or salary.get("basis") != "PRE_TAX_BASE_MONTHLY":
        raise DomainError("salary currency/basis must be explicitly confirmed")
    if salary.get("comparison") not in {"GTE", "GT"}:
        raise DomainError("salary comparison must be GTE or GT")
    minimum = salary.get("minimum")
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or minimum < 0:
        raise DomainError("salary minimum must be nonnegative number")
    if salary.get("unknown_policy") not in {"REVIEW_BUCKET", "EXCLUDE"}:
        raise DomainError("unknown salary policy must be confirmed")
    target = preferences.get("batch_target_count", 50)
    if type(target) is not int or not 1 <= target <= 500:
        raise DomainError("batch_target_count must be an integer from 1 to 500")


def job_identity(job: dict[str, Any]) -> str:
    """Use a source job ID when available, otherwise a conservative stable key."""
    source_id = str(job.get("platform_job_id") or "").strip()
    platform = str(job.get("source_platform") or "").strip().lower()
    if source_id and platform:
        seed = [platform, source_id]
    else:
        company = str(job.get("company") or "").strip().casefold()
        title = str(job.get("title") or "").strip().casefold()
        city = str(job.get("city") or "").strip().casefold()
        jd_digest = str(job.get("jd_sha256") or "").strip().lower()
        if not company or not title or not city or not jd_digest:
            raise DomainError("job without platform ID needs verified company/title/city/JD digest")
        seed = [company, title, city, jd_digest]
    return "JOB-" + stable_hash(seed)[:20].upper()


_MONTHLY_RAW_PATTERN = None  # compiled lazily to keep import cost off module load


def _monthly_notation_basis(job: dict[str, Any]) -> bool:
    """Owner-approved relaxation 2026-09-28: a quoted salary written as
    "12K-20K/月" / "7千-9千/月" / "10000元/月" is the industry-standard monthly
    base notation; treat it as PRE_TAX_BASE_MONTHLY unless the quote itself
    says after-tax or annual (年薪/税后/年). Evidence stays the quoted raw text."""
    global _MONTHLY_RAW_PATTERN
    raw = job.get("salary_raw")
    if not isinstance(raw, str) or job.get("salary_min_monthly") is None:
        return False
    if any(mark in raw for mark in ("税后", "年薪", "/年", "每年", "年度")):
        return False
    if _MONTHLY_RAW_PATTERN is None:
        import re
        _MONTHLY_RAW_PATTERN = re.compile(r"(?:/月|每月|月薪|月薪范围|个月)")
    return bool(_MONTHLY_RAW_PATTERN.search(raw))


def _salary_check(job: dict[str, Any], campaign: dict[str, Any]) -> str:
    salary = job.get("salary_min_monthly")
    basis = job.get("salary_basis")
    if basis != "PRE_TAX_BASE_MONTHLY" and not _monthly_notation_basis(job):
        return "UNKNOWN"
    if salary is None or isinstance(salary, bool) or not isinstance(salary, (int, float)):
        return "UNKNOWN"
    floor = campaign["salary"]["minimum"]
    compare = campaign["salary"]["comparison"]
    return "MATCH" if (salary >= floor if compare == "GTE" else salary > floor) else "MISMATCH"


def _eligibility_check(job: dict[str, Any], campaign: dict[str, Any]) -> str:
    recruitment = job.get("recruitment_type")
    if recruitment in {"INTERNSHIP", "SOCIAL"}:
        return "MISMATCH"
    if recruitment != "AUTUMN_CAMPUS":
        return "UNKNOWN"
    years = job.get("graduation_years")
    if years is None:
        return "UNKNOWN"
    if 2027 not in years:
        return "MISMATCH"
    required_degree = job.get("required_degree")
    if required_degree in {"MASTER", "PHD"}:
        return "MISMATCH"
    if required_degree not in {"BACHELOR", "ANY"}:
        return "UNKNOWN"
    experience = job.get("required_experience_years")
    if experience is None:
        # Owner-approved relaxation 2026-09-28: an AUTUMN_CAMPUS posting for the
        # target graduation year is by definition fresh-graduate hiring; a missing
        # explicit experience line no longer forces UNKNOWN. An explicit >0
        # requirement still mismatches.
        return "MATCH"
    if experience != 0:
        return "MISMATCH"
    city_scope = campaign["city_scope"]
    if city_scope["mode"] == "CITIES" and job.get("city") not in city_scope["values"]:
        return "MISMATCH" if job.get("city") else "UNKNOWN"
    if city_scope["mode"] == "REMOTE" and job.get("remote") is not True:
        return "MISMATCH" if job.get("remote") is False else "UNKNOWN"
    return "MATCH"


def _scope_check(job: dict[str, Any], campaign: dict[str, Any]) -> str:
    if job.get("role_match") == "MISMATCH":
        return "MISMATCH"
    if job.get("role_match") != "MATCH" or not job.get("role_match_evidence"):
        return "UNKNOWN"
    family = job.get("role_family")
    adjacent_key = {"FRONTEND": "frontend", "ALGORITHM": "algorithm", "SALES": "sales"}.get(family)
    if adjacent_key and not campaign["adjacent_role_policy"][adjacent_key]:
        return "MISMATCH"
    if family is None:
        return "UNKNOWN"
    if campaign["company_scope"] == "FILTERED":
        filters = campaign["company_filters"]
        if filters.get("names") and job.get("company") not in filters["names"]:
            return "MISMATCH" if job.get("company") else "UNKNOWN"
        if filters.get("sizes") and job.get("company_size") not in filters["sizes"]:
            return "MISMATCH" if job.get("company_size") else "UNKNOWN"
    return "MATCH"


def classify_job(job: dict[str, Any], campaign: dict[str, Any]) -> dict[str, Any]:
    """Normalize one found job without inventing eligibility or salary evidence."""
    result = dict(job)
    result["job_id"] = job_identity(result)
    result["salary_check"] = _salary_check(result, campaign)
    result["eligibility_check"] = _eligibility_check(result, campaign)
    result["scope_check"] = _scope_check(result, campaign)
    risks: list[str] = []
    if result["salary_check"] == "MISMATCH":
        risks.append("SALARY_BELOW_CONFIRMED_MINIMUM")
    elif result["salary_check"] == "UNKNOWN":
        risks.append("SALARY_NOT_VERIFIED")
    if result["eligibility_check"] == "MISMATCH":
        risks.append("RECRUITMENT_OR_QUALIFICATION_MISMATCH")
    elif result["eligibility_check"] == "UNKNOWN":
        risks.append("ELIGIBILITY_NOT_VERIFIED")
    if result["scope_check"] == "MISMATCH":
        risks.append("ROLE_OR_COMPANY_SCOPE_MISMATCH")
    elif result["scope_check"] == "UNKNOWN":
        risks.append("ROLE_OR_COMPANY_SCOPE_NOT_VERIFIED")
    if not result.get("source_url"):
        risks.append("SOURCE_URL_MISSING")
    if result.get("opening_status") == "CLOSED":
        risks.append("CLOSED")
    elif result.get("opening_status") != "OPEN":
        # Owner-approved relaxation 2026-09-28: campus postings without an explicit
        # status line stay flagged for the Owner's G1 eyes but no longer force the
        # unknown pool; only an explicit CLOSED excludes.
        risks.append("OPENING_STATUS_NOT_VERIFIED")
    if not result.get("company"):
        risks.append("EMPLOYER_MISSING")
    if result.get("jd_completeness") != "FULL":
        risks.append("JD_INCOMPLETE")
    salary_unknown_excluded = result["salary_check"] == "UNKNOWN" and campaign["salary"]["unknown_policy"] == "EXCLUDE"
    if salary_unknown_excluded:
        risks.append("SALARY_UNKNOWN_EXCLUDED_BY_OWNER_POLICY")
    if "MISMATCH" in (result["salary_check"], result["eligibility_check"], result["scope_check"]) or salary_unknown_excluded or any(r in risks for r in ("CLOSED", "SOURCE_URL_MISSING", "EMPLOYER_MISSING")):
        pool = "excluded"
    elif "UNKNOWN" in (result["salary_check"], result["eligibility_check"], result["scope_check"]):
        # Owner-approved relaxation 2026-09-28: OPENING_STATUS_NOT_VERIFIED and
        # JD_INCOMPLETE no longer force the unknown pool — the Owner reviews them
        # at G1 and M2 re-fetches the full JD from the company source anyway.
        pool = "unknown"
    else:
        pool = "qualified"
    result["pool"] = pool
    result["risk_flags"] = risks
    result.setdefault("captured_at", utc_now())
    return result


def make_batch(campaign: dict[str, Any], found_jobs: list[dict[str, Any]], batch_id: str) -> dict[str, Any]:
    if campaign.get("status") != "PREFERENCE_CONFIRMED":
        raise DomainError("G0 confirmation required before discovery")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", batch_id):
        raise DomainError("invalid batch_id")
    jobs: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    for raw in found_jobs:
        job = classify_job(raw, campaign)
        key = job["job_id"]
        if key in jobs:
            originals = jobs[key].setdefault("source_refs", [])
            ref = {"source_url": job.get("source_url"), "source_platform": job.get("source_platform")}
            if ref not in originals:
                originals.append(ref)
            duplicates.append({"job_id": key, "source_url": job.get("source_url")})
        else:
            job["source_refs"] = [{"source_url": job.get("source_url"), "source_platform": job.get("source_platform")}]
            jobs[key] = job
    counts = {pool: sum(j["pool"] == pool for j in jobs.values()) for pool in ("qualified", "unknown", "excluded")}
    return {"schema": "candidate-batch@1", "batch_id": batch_id, "revision": 1,
            "campaign_id": campaign["campaign_id"], "campaign_revision": campaign["revision"],
            "created_at": utc_now(), "target_count": campaign.get("batch_target_count", 50),
            "jobs": jobs, "counts": counts, "duplicates": duplicates,
            "target_shortfall": max(0, campaign.get("batch_target_count", 50) - counts["qualified"])}

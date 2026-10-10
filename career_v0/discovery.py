"""Read DSH Search/Fetch event traces as source leads, never as qualified jobs."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

from .domain import utc_now


class DiscoveryError(ValueError):
    pass


LINK = re.compile(r"^- \[([^\]\n]+)\]\((https?://[^\s)]+)\)", re.MULTILINE)
FETCH = re.compile(r"^Fetched (https?://\S+) \(HTTP (\d{3})\)")


def _url(value: Any) -> str:
    if not isinstance(value, str):
        raise DiscoveryError("source URL is missing")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise DiscoveryError("source URL must be HTTP(S)")
    return value


def parse_dsh_events(data: bytes) -> list[dict[str, Any]]:
    if not data or len(data) > 20 * 1024 * 1024:
        raise DiscoveryError("DSH event trace missing or larger than 20 MB")
    events = []
    try:
        lines = data.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise DiscoveryError("DSH event trace is not UTF-8") from exc
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DiscoveryError(f"invalid DSH event at line {line_no}") from exc
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise DiscoveryError(f"invalid DSH event object at line {line_no}")
        events.append(event)
    return events


def minimal_event_trace(events: list[dict[str, Any]], *, keep_final: bool = False) -> bytes:
    """Persist source evidence without model thinking, session state or status chatter."""
    allowed = {"tool_call", "tool_result"}
    if keep_final:
        allowed.add("final")
    selected = [event for event in events if event.get("type") in allowed]
    if not selected:
        raise DiscoveryError("DSH trace contains no persistable source events")
    return ("\n".join(json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                      for event in selected) + "\n").encode("utf-8")


def source_records(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Pair actual tool calls/results; return leads and fetches with raw hashes."""
    calls = {event.get("callId"): event for event in events
             if event.get("type") == "tool_call" and event.get("callId")}
    leads: list[dict[str, Any]] = []
    captures: list[dict[str, Any]] = []
    seen_leads: set[str] = set()
    for event in events:
        if event.get("type") != "tool_result" or event.get("status") != "completed":
            continue
        call_id = event.get("callId")
        call = calls.get(call_id)
        if call is None:
            raise DiscoveryError("DSH tool result has no matching call")
        tool = call.get("tool")
        result = event.get("result")
        if not isinstance(result, str):
            continue
        digest = hashlib.sha256(result.encode("utf-8")).hexdigest()
        if tool == "web_search":
            queries = call.get("input", {}).get("queries")
            if not isinstance(queries, list):
                raise DiscoveryError("web_search queries missing")
            for title, source_url in LINK.findall(result):
                source_url = _url(source_url)
                if source_url in seen_leads:
                    continue
                seen_leads.add(source_url)
                leads.append({"title_hint": title, "source_url": source_url,
                              "search_queries": queries, "call_id": call_id,
                              "result_sha256": digest, "status": "SEARCH_LEAD_ONLY"})
        elif tool == "web_fetch":
            requested_url = _url(call.get("input", {}).get("url"))
            match = FETCH.match(result)
            returned_url = _url(match.group(1)) if match else requested_url
            status_code = int(match.group(2)) if match else None
            # A 200 response with empty or truncated text is not a full JD.
            body = result.split("External web content follows.", 1)[-1].strip() if match else ""
            complete = status_code == 200 and len(body) >= 200 and "Content truncated." not in body
            captures.append({"capture_id": "CAP-" + digest[:20].upper(),
                             "requested_url": requested_url, "source_url": returned_url,
                             "http_status": status_code, "content_state": "FETCHED_TEXT" if complete else "INCOMPLETE",
                             "raw_result_sha256": digest, "raw_result": result,
                             "content_text": body,
                             "captured_at": utc_now(), "call_id": call_id})
    return {"schema": "dsh-source-records@1", "leads": leads, "captures": captures,
            "qualified_job_count": 0}


def _markdown_relaxed_hit(quote: str, content: str) -> bool:
    """Verbatim hit ignoring markdown emphasis wrappers: the extraction model
    strips **bold**/**italic** markers the page renders as styling, so compare
    with formatting characters removed from both sides. Content words must still
    match character for character."""
    if quote in content:
        return True
    strip = str.maketrans("", "", "*`")
    return quote.translate(strip) in content.translate(strip)


def _quoted_section(value: Any, content: str) -> bool:
    """A section counts as quoted when it is one verbatim span of the capture,
    or a list whose every line occurs verbatim in the capture (the extraction
    model naturally returns one item per bullet). Both bind every claimed line
    to the captured page, so either form proves the section came from it."""
    if isinstance(value, str):
        return len(value) >= 10 and _markdown_relaxed_hit(value, content)
    if isinstance(value, list) and value:
        return all(isinstance(item, str) and len(item) >= 8 and _markdown_relaxed_hit(item, content) for item in value)
    return False


def ground_job(raw: dict[str, Any], discovery: dict[str, Any]) -> dict[str, Any]:
    """Discard proposed hard facts whose quoted source span is unavailable."""
    source_url = _url(raw.get("source_url"))
    if source_url not in {lead["source_url"] for lead in discovery["leads"]} and source_url not in {cap["source_url"] for cap in discovery["captures"]}:
        raise DiscoveryError("job URL is not present in the DSH discovery trace")
    capture = next((cap for cap in discovery["captures"] if cap["source_url"] == source_url and cap["content_state"] == "FETCHED_TEXT"), None)
    job = dict(raw)
    job["source_platform"] = urlsplit(source_url).hostname
    platform_id = job.get("platform_job_id")
    if not isinstance(platform_id, str) or not platform_id.strip() or (platform_id not in source_url and platform_id not in (capture["content_text"] if capture else "")):
        job.pop("platform_job_id", None)
    quote_map = raw.get("field_evidence") or {}
    grounded: dict[str, str] = {}
    hard_fields = (
        "company", "title", "city", "recruitment_type", "graduation_years",
        "required_degree", "required_experience_years", "salary_raw",
        "salary_min_monthly", "salary_basis", "opening_status", "role_match",
        "role_family", "company_size",
    )
    content = capture["content_text"] if capture else ""
    for field in hard_fields:
        quote = quote_map.get(field) if isinstance(quote_map, dict) else None
        # Evidence may be one verbatim span or a list of verbatim spans (the
        # extraction model splits multi-line evidence into items); markdown
        # emphasis characters are ignored. Items are validated individually —
        # their join spans separate page regions, so the join is not re-checked.
        if isinstance(quote, list) and quote and all(
                isinstance(item, str) and len(item.strip()) >= 2 and _markdown_relaxed_hit(item, content)
                for item in quote):
            grounded[field] = "\n".join(quote)
            continue
        if not isinstance(quote, str) or len(quote.strip()) < 2 or not _markdown_relaxed_hit(quote, content):
            job.pop(field, None)
        else:
            grounded[field] = quote
    for field in ("company", "title", "city", "role_family", "company_size"):
        if field in job and (not isinstance(job[field], str) or not job[field].strip()):
            job.pop(field, None)
            grounded.pop(field, None)
    years = job.get("graduation_years")
    if years is not None and (not isinstance(years, list) or not years or any(type(year) is not int or str(year) not in grounded.get("graduation_years", "") for year in years)):
        job.pop("graduation_years", None)
        grounded.pop("graduation_years", None)
    recruitment = job.get("recruitment_type")
    recruitment_markers = {"AUTUMN_CAMPUS": ("秋招", "校招", "校园招聘"),
                           "INTERNSHIP": ("实习",), "SOCIAL": ("社招", "社会招聘")}
    if not isinstance(recruitment, str) or recruitment not in recruitment_markers or not any(marker in grounded.get("recruitment_type", "") for marker in recruitment_markers[recruitment]):
        job.pop("recruitment_type", None)
        grounded.pop("recruitment_type", None)
    if not isinstance(job.get("role_match"), str) or job["role_match"] not in {"MATCH", "MISMATCH"}:
        job.pop("role_match", None)
        grounded.pop("role_match", None)
    if not isinstance(job.get("opening_status"), str) or job["opening_status"] not in {"OPEN", "CLOSED"}:
        job.pop("opening_status", None)
        grounded.pop("opening_status", None)
    if job.get("required_degree") not in ("BACHELOR", "MASTER", "PHD", "ANY"):
        job.pop("required_degree", None)
        grounded.pop("required_degree", None)
    if job.get("role_family") not in ("AI_AGENT_DEV", "AI_APP_ENGINEER", "AI_PRODUCT_MANAGER", "FRONTEND", "ALGORITHM", "SALES"):
        job.pop("role_family", None)
        grounded.pop("role_family", None)
    if type(job.get("required_experience_years")) is not int or job.get("required_experience_years", 0) < 0:
        job.pop("required_experience_years", None)
        grounded.pop("required_experience_years", None)
    salary_min = job.get("salary_min_monthly")
    if type(salary_min) not in {int, float} or salary_min < 0:
        job.pop("salary_min_monthly", None)
        grounded.pop("salary_min_monthly", None)
    elif "salary_min_monthly" in grounded:
        salary_quote = grounded["salary_min_monthly"]
        if any(token in salary_quote for token in ("/天", "每天", "/年", "年薪", "日薪")):
            job.pop("salary_min_monthly", None)
            grounded.pop("salary_min_monthly", None)
        else:
            match = re.search(r"(\d+(?:\.\d+)?)\s*(k|K|千|万|元)", salary_quote)
            multiplier = {"k": 1000, "K": 1000, "千": 1000, "万": 10000, "元": 1}
            parsed = float(match.group(1)) * multiplier[match.group(2)] if match else None
            if parsed is None or abs(parsed - salary_min) > 0.001:
                job.pop("salary_min_monthly", None)
                grounded.pop("salary_min_monthly", None)
    experience = job.get("required_experience_years")
    if experience == 0 and "required_experience_years" in grounded and not any(
        marker in grounded["required_experience_years"] for marker in ("经验不限", "无需经验", "应届", "0年", "零经验")
    ):
        job.pop("required_experience_years", None)
        grounded.pop("required_experience_years", None)
    if isinstance(experience, int) and experience > 0 and "required_experience_years" in grounded and str(experience) not in grounded["required_experience_years"]:
        job.pop("required_experience_years", None)
        grounded.pop("required_experience_years", None)
    degree_markers = {"BACHELOR": ("本科", "学士"), "MASTER": ("硕士",), "PHD": ("博士",), "ANY": ("学历不限", "不限学历")}
    degree = job.get("required_degree")
    if degree in degree_markers and "required_degree" in grounded and not any(marker in grounded["required_degree"] for marker in degree_markers[degree]):
        job.pop("required_degree", None)
        grounded.pop("required_degree", None)
    if job.get("salary_basis") == "PRE_TAX_BASE_MONTHLY" and "salary_basis" in grounded:
        salary_quote = grounded["salary_basis"]
        if not all(marker in salary_quote for marker in ("税前", "月")) or not any(marker in salary_quote for marker in ("基本", "底薪", "固定")):
            job.pop("salary_basis", None)
            grounded.pop("salary_basis", None)
    if job.get("opening_status") == "OPEN" and "opening_status" in grounded and not any(
        marker in grounded["opening_status"] for marker in ("招聘中", "正在招聘", "投递中", "接受投递")
    ):
        job.pop("opening_status", None)
        grounded.pop("opening_status", None)
    if "role_match" in grounded:
        job["role_match_evidence"] = grounded["role_match"]
    else:
        job.pop("role_match_evidence", None)
    sections = raw.get("jd_sections") or {}
    if not capture or not isinstance(sections, dict):
        job["jd_completeness"] = "PARTIAL"
    elif all(_quoted_section(sections.get(key), content) for key in ("responsibilities", "requirements")):
        job["jd_completeness"] = "FULL"
        job["jd_sha256"] = capture["raw_result_sha256"]
    else:
        job["jd_completeness"] = "PARTIAL"
    job["source_capture_id"] = capture["capture_id"] if capture else None
    job["source_content_sha256"] = capture["raw_result_sha256"] if capture else None
    job["captured_at"] = capture["captured_at"] if capture else utc_now()
    job["grounded_fields"] = grounded
    return job

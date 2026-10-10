"""Read-only master project candidates; Owner decides the actual G0 inventory."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .domain import DomainError


SECTION = re.compile(r"^#\s*(项目经历|其他项目)\s*$")
PROJECT = re.compile(r"^###\s*(\S.*)$")  # accepts the existing '###Local' heading
CHILD = re.compile(r"^\*\*(.+?)\*\*\s*$")


def _name(heading: str) -> str:
    return re.split(r"\s*——|\s*[：:]", heading, maxsplit=1)[0].strip()


def candidate_inventory(master_bytes: bytes) -> dict[str, Any]:
    if not master_bytes:
        raise DomainError("master resume is empty")
    text = master_bytes.decode("utf-8-sig")
    lines = text.splitlines()
    master_sha = hashlib.sha256(master_bytes).hexdigest()
    projects: list[dict[str, Any]] = []
    section: str | None = None
    for number, line in enumerate(lines, 1):
        section_match = SECTION.match(line.strip())
        if section_match:
            section = section_match.group(1)
            continue
        if line.startswith("# "):
            section = None
        heading = PROJECT.match(line)
        if not section or not heading:
            continue
        name = _name(heading.group(1))
        if not name:
            raise DomainError(f"empty project heading at line {number}")
        project_id = "PROJ-" + hashlib.sha256(name.casefold().encode()).hexdigest()[:12].upper()
        if any(item["project_id"] == project_id for item in projects):
            raise DomainError(f"duplicate project heading: {name}")
        projects.append({"project_id": project_id, "name": name,
                         "original_index": len(projects) + 1, "purpose": None,
                         "core_stack": None, "status": None, "include_in_resume": None,
                         "source": {"master_sha256": master_sha, "section": section,
                                    "heading_line": number}, "child_candidates": []})
    for index, item in enumerate(projects):
        start = item["source"]["heading_line"]
        end = projects[index + 1]["source"]["heading_line"] - 1 if index + 1 < len(projects) else len(lines)
        body = lines[start:end]
        item["source"]["end_line"] = end
        item["source"]["content_sha256"] = hashlib.sha256("\n".join(body).encode()).hexdigest()
        for offset, line in enumerate(body, start + 1):
            child = CHILD.match(line.strip())
            if child:
                item["child_candidates"].append({"name": child.group(1), "source_line": offset,
                                                 "owner_decision": None})
    return {"schema": "project-inventory-candidate@1", "master_sha256": master_sha,
            "projects": projects, "candidate_count": len(projects),
            "owner_confirmed": False}


def validate_confirmed_inventory(inventory: dict[str, Any], candidate: dict[str, Any]) -> None:
    """Fail G0 if a candidate or nested item disappears without an Owner choice."""
    if inventory.get("master_sha256") != candidate["master_sha256"]:
        raise DomainError("project inventory master version mismatch")
    project_rows = inventory.get("projects")
    if not isinstance(project_rows, list):
        raise DomainError("project inventory missing")
    expected = {item["project_id"] for item in candidate["projects"]}
    actual = {item.get("project_id") for item in project_rows if isinstance(item, dict)}
    if len(project_rows) != len(expected) or actual != expected:
        raise DomainError("project inventory candidate ID set changed")
    source_by_id = {item["project_id"]: item for item in candidate["projects"]}
    selected = 0
    for item in project_rows:
        original = source_by_id[item["project_id"]]
        if item.get("name") != original["name"] or item.get("original_index") != original["original_index"]:
            raise DomainError("project identity or source order changed")
        if type(item.get("include_in_resume")) is not bool:
            raise DomainError(f"project {item['project_id']} requires an explicit include decision")
        if item["include_in_resume"]:
            selected += 1
        if not isinstance(item.get("purpose"), str) or not item["purpose"].strip():
            raise DomainError(f"project {item['project_id']} purpose missing")
        if (not isinstance(item.get("core_stack"), list) or not item["core_stack"]
                or any(not isinstance(stack, str) or not stack.strip() for stack in item["core_stack"])):
            raise DomainError(f"project {item['project_id']} core stack missing")
        if item.get("status") not in {"COMPLETED", "PARTIALLY_VERIFIED", "IN_PROGRESS", "EXPLORING"}:
            raise DomainError(f"project {item['project_id']} status missing")
        if item.get("source") != original["source"]:
            raise DomainError(f"project {item['project_id']} source differs from master")
        child_rows = item.get("child_candidates")
        original_children = original["child_candidates"]
        if not isinstance(child_rows, list) or [row.get("name") for row in child_rows] != [row["name"] for row in original_children]:
            raise DomainError(f"project {item['project_id']} nested candidates changed")
        if any(row.get("owner_decision") not in {"SUBPROJECT", "INDEPENDENT", "OUT_OF_SCOPE"} for row in child_rows):
            raise DomainError(f"project {item['project_id']} nested candidates need Owner decisions")
    if selected == 0:
        raise DomainError("project inventory cannot select zero projects")

"""Build a conservative, source-linked resume view from an approved V-0 plan."""

from __future__ import annotations

import html
import re
from typing import Any


class ResumeContentError(ValueError):
    pass


_MARKUP = re.compile(r"\*\*(.*?)\*\*")


def _plain(value: str) -> str:
    value = _MARKUP.sub(r"\1", value.strip())
    return re.sub(r"\s+", " ", value).strip()


def _section(lines: list[str], title: str, stop_prefixes: tuple[str, ...]) -> list[tuple[int, str]]:
    start = next((i for i, line in enumerate(lines) if line.strip() == title), None)
    if start is None:
        raise ResumeContentError(f"master section missing: {title}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(stop_prefixes)), len(lines))
    return [(i + 1, lines[i]) for i in range(start + 1, end) if lines[i].strip()]


def _bullet_text(line: str) -> str:
    """Strip one leading bullet marker. The master mixes '- ' with '-'
    (no space) and other markers; content after the marker stays verbatim."""
    stripped = line.lstrip()
    for marker in ("- ", "-", "• ", "•", "* "):
        if stripped.startswith(marker):
            return stripped[len(marker):].lstrip()
    return stripped


def _project_bullets(lines: list[str], source: dict[str, Any]) -> list[tuple[int, str]]:
    start = source["heading_line"]
    end = source["end_line"]
    return [(number, _plain(_bullet_text(lines[number - 1]))) for number in range(start + 1, end + 1)
            if number <= len(lines) and lines[number - 1].lstrip().startswith(("- ", "-", "• ", "•", "* "))]


def build_resume_content(master_bytes: bytes, campaign: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    lines = master_bytes.decode("utf-8-sig").splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ResumeContentError("master name heading missing")
    if plan["constraints"]["preserve_section_order"] is not True or plan["constraints"]["preserve_retained_bullet_order"] is not True:
        raise ResumeContentError("this renderer needs the approved default section and bullet order")
    inventory = {item["project_id"]: item for item in campaign["project_inventory"]["projects"]
                 if item["include_in_resume"]}
    project_plan = plan["project_plan"]
    if {row["project_id"] for row in project_plan} != set(inventory) or len(project_plan) != len(inventory):
        raise ResumeContentError("approved project plan does not cover the confirmed inventory")
    if plan["constraints"]["preserve_project_order"] is True and [row["project_id"] for row in project_plan] != [
        item["project_id"] for item in sorted(inventory.values(), key=lambda item: item["original_index"])
    ]:
        raise ResumeContentError("approved project order differs from confirmed inventory")
    contact = next((line.strip() for line in lines[1:7] if "@" in line), "")
    if not contact:
        raise ResumeContentError("master contact line missing")
    highlights = campaign["resume_profile"]["identity_signals"]
    highlight_blocks = [{"text": row["approved_expression"], "evidence_id": "PROFILE-" + signal_id}
                        for signal_id, row in highlights.items()]
    if set(highlights) != {"ID-PLATFORMS", "ID-PROJECTS", "ID-PROVENANCE"}:
        raise ResumeContentError("all three protected signals are required")
    education_lines = _section(lines, "## 教育背景", ("## 核心能力", "# 项目经历"))
    internship_heading = next((i for i, (_, line) in enumerate(education_lines) if "实习经历" in line), None)
    if internship_heading is None:
        raise ResumeContentError("master internship section missing")
    education = [{"text": _plain(line.removeprefix("- ")), "master_line": number}
                 for number, line in education_lines[:internship_heading]]
    internship = education_lines[internship_heading:]
    internship_head = _plain(internship[0][1])
    internship_intro = _plain(internship[1][1]) if len(internship) > 1 and not internship[1][1].startswith("- ") else ""
    internship_bullets = [{"text": _plain(line[2:]), "master_line": number}
                          for number, line in internship if line.startswith("- ")]
    internship_plan = next((row for row in plan["section_plan"] if row["section_id"] == "internship"), None)
    if internship_plan is None:
        raise ResumeContentError("approved internship plan missing")
    if internship_plan["action"] == "COMPRESS":
        internship_bullets = internship_bullets[:internship_plan["target_bullets"]]
    skills_lines = _section(lines, "## 核心能力", ("# 项目经历",))
    skills = [{"text": _plain(line), "master_line": number} for number, line in skills_lines]
    projects = []
    for row in project_plan:
        item = inventory[row["project_id"]]
        bullets = _project_bullets(lines, item["source"])
        if row["tier"] == "HERO":
            if not bullets:
                raise ResumeContentError(f"HERO project {row['project_id']} has no source bullets")
            terms = [term.casefold() for term in row.get("emphasis", []) if isinstance(term, str)]
            ranked = sorted(bullets, key=lambda pair: (-sum(term in pair[1].casefold() for term in terms), pair[0]))
            chosen = sorted(ranked[:row["target_bullets"]], key=lambda pair: pair[0])
            content = [{"text": bullet, "master_line": number} for number, bullet in chosen]
        else:
            content = []
        projects.append({"project_id": row["project_id"], "name": item["name"],
                         "section": item["source"]["section"], "tier": row["tier"],
                         "status": item["status"], "purpose": item["purpose"],
                         "core_stack": item["core_stack"], "bullets": content,
                         "evidence_id": "MASTER-" + row["project_id"],
                         "source_order": item["original_index"]})
    return {"name": _plain(lines[0][2:]), "contact": _plain(contact),
            "target": " / ".join(campaign["target_roles"]) + f"｜{campaign['graduation_year']} 届秋招",
            "highlights": highlight_blocks, "education": education,
            "internship": {"heading": internship_head, "intro": internship_intro,
                           "bullets": internship_bullets},
            "skills": skills, "projects": projects,
            "project_ids": [item["project_id"] for item in projects]}


def content_html(content: dict[str, Any], plan: dict[str, Any]) -> str:
    escape = html.escape
    font = plan["layout_plan"]["font_size_pt"]
    blocks = ["<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
              "<style>@page{size:A4;margin:12mm 14mm}*{box-sizing:border-box}",
              f"body{{margin:0;color:#1c2730;font-family:'Microsoft YaHei','SimSun',sans-serif;font-size:{font}pt;line-height:1.25}}",
              "h1{font-size:18pt;margin:0 0 2pt}h2{font-size:11.5pt;margin:5pt 0 2pt;border-bottom:.6pt solid #56788c;break-after:avoid}",
              "h3{font-size:10.5pt;margin:4pt 0 1pt;break-after:avoid}p{margin:0 0 2pt}",
              ".bullet{padding-left:9pt;text-indent:-9pt}.bullet:before{content:'• ';color:#476b82}",
              ".project{break-inside:avoid}.compact{font-size:.96em}.meta{font-size:9pt;color:#53606d}",
              "</style></head><body>",
              f"<h1>{escape(content['name'])}</h1><p class='meta'>{escape(content['contact'])}</p>",
              f"<p class='meta'>{escape(content['target'])}</p><h2>求职亮点</h2>"]
    for item in content["highlights"]:
        blocks.append(f"<p class='bullet' data-evidence='{escape(item['evidence_id'])}'>{escape(item['text'])}</p>")
    blocks.append("<h2>教育背景</h2>")
    for item in content["education"]:
        blocks.append(f"<p data-master-line='{item['master_line']}'>{escape(item['text'])}</p>")
    blocks.append(f"<h3>{escape(content['internship']['heading'])}</h3>")
    if content["internship"]["intro"]:
        blocks.append(f"<p>{escape(content['internship']['intro'])}</p>")
    for item in content["internship"]["bullets"]:
        blocks.append(f"<p class='bullet' data-master-line='{item['master_line']}'>{escape(item['text'])}</p>")
    blocks.append("<h2>核心能力</h2>")
    for item in content["skills"]:
        blocks.append(f"<p data-master-line='{item['master_line']}'>{escape(item['text'])}</p>")
    current_section = None
    for item in content["projects"]:
        if item["section"] != current_section:
            current_section = item["section"]
            blocks.append(f"<h2>{escape(current_section)}</h2>")
        blocks.append(f"<div class='project {item['tier'].lower()}' data-project-id='{escape(item['project_id'])}' data-tier='{item['tier']}'>")
        status = "" if item["status"] == "COMPLETED" else f"｜{item['status']}"
        blocks.append(f"<h3>{escape(item['name'] + status)}</h3>")
        if item["tier"] == "COMPACT":
            # The plan budgets COMPACT at target_lines (2); purpose is the
            # Owner-confirmed fact and always renders, while the stack list
            # yields to the line budget (it is decorative here — HERO rows and
            # 核心能力 already carry the stack facts verbatim).
            stack_text = " / ".join(item["core_stack"])
            text = f"用途：{escape(item['purpose'])}"
            if len(item["purpose"]) + len(stack_text) <= 74:
                text += f"；技术栈：{escape(stack_text)}"
            blocks.append(f"<p class='compact'>{text}</p>")
        else:
            for bullet in item["bullets"]:
                blocks.append(f"<p class='bullet' data-master-line='{bullet['master_line']}'>{escape(bullet['text'])}</p>")
        blocks.append("</div>")
    blocks.append("</body></html>")
    return "".join(blocks)

"""Render and inspect one approved content source; never force a third page into final."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pdfplumber
import pypdfium2 as pdfium


class ResumeRenderError(ValueError):
    pass


def render_and_inspect(html_path: Path, pdf_path: Path, *, expected_project_ids: list[str],
                       expected_text: list[str], timeout_seconds: int = 90) -> dict[str, Any]:
    node = os.environ.get("CAREER_NODE_BIN") or shutil.which("node")
    if not node:
        raise ResumeRenderError("Node runtime not configured for PDF rendering")
    script = Path(__file__).with_name("render_resume.mjs")
    try:
        result = subprocess.run([node, str(script), str(html_path), str(pdf_path)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ResumeRenderError("PDF renderer timed out") from exc
    if result.returncode != 0 or not pdf_path.is_file():
        raise ResumeRenderError("PDF renderer failed: " + result.stderr.decode("utf-8", "replace")[-500:])
    try:
        dom = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResumeRenderError("PDF renderer did not return valid DOM metrics") from exc
    if dom.get("projectIds") != expected_project_ids:
        raise ResumeRenderError("rendered project ID order differs from approved content")
    compact_overflow = [row for row in dom.get("compactLineCounts", []) if row["lines"] > 2]
    with pdfplumber.open(pdf_path) as document:
        page_count = len(document.pages)
        sizes = [[round(page.width, 2), round(page.height, 2)] for page in document.pages]
        text = "\n".join(page.extract_text() or "" for page in document.pages)
        page_text_lengths = [len(page.extract_text() or "") for page in document.pages]
    compact_text = re.sub(r"\s+", "", text)
    missing_text = [item for item in expected_text if item and re.sub(r"\s+", "", item) not in compact_text]
    a4 = all(abs(width - 595.28) < 2 and abs(height - 841.89) < 2 for width, height in sizes)
    problems = []
    if page_count != 2:
        problems.append(f"PAGE_COUNT_{page_count}_EXPECTED_2")
    if not a4:
        problems.append("NOT_A4")
    if compact_overflow:
        problems.append("COMPACT_OVER_2_LINES")
    if missing_text:
        problems.append("EXPECTED_TEXT_MISSING")
    if any(length < 100 for length in page_text_lengths):
        problems.append("SPARSE_OR_EMPTY_PAGE")
    if page_count > 20:
        raise ResumeRenderError("PDF has more than 20 pages; page-image review cannot be completed")
    page_image_paths = []
    page_image_sha256 = []
    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
        if len(pdf) != page_count:
            raise ResumeRenderError("PDF page-image count differs from text inspection")
        for index in range(page_count):
            target = pdf_path.with_name(f"{pdf_path.stem}-page-{index + 1}.png")
            page = pdf[index]
            page.render(scale=1.5).to_pil().save(target, format="PNG")
            page.close()
            page_image_paths.append(str(target))
            page_image_sha256.append(hashlib.sha256(target.read_bytes()).hexdigest())
        pdf.close()
    except Exception as exc:
        raise ResumeRenderError("PDF page-image rendering failed") from exc
    return {"status": "NEEDS_PLAN_REVISION" if problems else "WAITING_VISUAL_REVIEW",
            "page_count": page_count, "page_sizes_pt": sizes,
            "page_text_lengths": page_text_lengths, "hero_count": dom.get("heroCount"),
            "project_ids": dom["projectIds"], "compact_line_counts": dom.get("compactLineCounts", []),
            "compact_overflow": compact_overflow, "missing_text": missing_text,
            "page_image_paths": page_image_paths,
            "page_image_sha256": page_image_sha256, "problems": problems}

"""Owner-confirmed resume facts and evidence IDs bound to the master revision."""

from __future__ import annotations

import hashlib
from typing import Any

from .domain import DomainError


SIGNALS = ("ID-PLATFORMS", "ID-PROJECTS", "ID-PROVENANCE")


def validate_identity_signals(signals: dict[str, Any], master_bytes: bytes) -> None:
    if not isinstance(signals, dict) or set(signals) != set(SIGNALS):
        raise DomainError("all three protected identity signals need Owner confirmation")
    master_text = master_bytes.decode("utf-8-sig")
    for signal_id in SIGNALS:
        row = signals[signal_id]
        if not isinstance(row, dict) or row.get("owner_confirmed") is not True:
            raise DomainError(f"{signal_id} needs explicit Owner confirmation")
        phrase = row.get("source_quote")
        if not isinstance(phrase, str) or len(phrase.strip()) < 4 or phrase not in master_text:
            raise DomainError(f"{signal_id} source quote not found in master")
        if not isinstance(row.get("approved_expression"), str) or not row["approved_expression"].strip():
            raise DomainError(f"{signal_id} approved expression missing")
    if "10+" not in signals["ID-PLATFORMS"]["source_quote"] and "10+" not in signals["ID-PLATFORMS"]["approved_expression"]:
        raise DomainError("platform count signal must remain explicit")
    if "7+" not in signals["ID-PROJECTS"]["source_quote"] and "7+" not in signals["ID-PROJECTS"]["approved_expression"]:
        raise DomainError("project count signal must remain explicit")


def build_resume_profile(campaign: dict[str, Any], master_bytes: bytes) -> dict[str, Any]:
    if campaign.get("status") != "PREFERENCE_CONFIRMED":
        raise DomainError("G0 confirmation required before Resume Profile")
    digest = hashlib.sha256(master_bytes).hexdigest()
    if digest != campaign.get("master_sha256"):
        raise DomainError("master changed after G0 confirmation")
    signals = campaign.get("identity_signals")
    validate_identity_signals(signals, master_bytes)
    inventory = campaign["project_inventory"]
    required = [row for row in inventory["projects"] if row["include_in_resume"]]
    refs = [{"evidence_id": "MASTER-" + row["project_id"],
             "source_type": "OWNER_MASTER", "source_ref": row["source"],
             "project_id": row["project_id"]} for row in required]
    refs.append({"evidence_id": "MASTER-INTERN-1", "source_type": "OWNER_MASTER",
                 "source_ref": {"master_sha256": digest, "section": "实习经历"}})
    refs.extend({"evidence_id": "PROFILE-" + signal_id,
                 "source_type": "OWNER_CONFIRMED_SIGNAL", "source_quote": signals[signal_id]["source_quote"],
                 "approved_expression": signals[signal_id]["approved_expression"]}
                for signal_id in SIGNALS)
    return {"schema": "owner-resume-profile@1", "campaign_id": campaign["campaign_id"],
            "campaign_revision": campaign["revision"], "revision": 1,
            "master_sha256": digest, "project_inventory_revision": campaign["revision"],
            "required_project_ids": [row["project_id"] for row in required],
            "identity_signals": signals, "owner_evidence": refs,
            "confirmed_by": campaign["confirmed_by"], "confirmed_at": campaign["confirmed_at"]}

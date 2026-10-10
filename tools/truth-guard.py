"""truth-guard - C3 fact auditor: Claim Extraction / Evidence Linking / Risk
Classification. Deterministic text analysis, no LLM.

Usage (stdin JSON, no path arguments):
  {"draft": "vault/drafts/ai-agent-v1.md", "master": "master_resume.md",
   "out": "runtime-proof/claims/report.json"}

Path model: fixed constants only.
  draft/out : project-root relative paths, validated to contain no traversal.
  master    : bare filename opened from the directory in CAREER_VAULT_DIR.
"""
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT_DIR = os.environ.get("CAREER_VAULT_DIR", "")


def is_bare(name):
    return (bool(name) and name not in (".", "..")
            and os.path.basename(name) == name
            and "/" not in name and "\\" not in name and ".." not in name)


def project_rel(path):
    if os.path.isabs(path):
        raise ValueError("absolute path not allowed: %s" % path)
    norm = os.path.normpath(path)
    if norm.startswith("..") or os.path.isabs(norm):
        raise ValueError("traversal rejected: %s" % path)
    root = os.path.realpath(PROJECT_ROOT)
    resolved = os.path.realpath(os.path.join(root, norm))
    if resolved != root and not resolved.startswith(root + os.sep):
        raise ValueError("traversal rejected: %s" % path)
    return resolved


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


NUM_RE = re.compile(r"\d+(?:[.,]\d+)?\s*[%万千亿年]|QPS\s*\d+|\d+\s*万")


def norm(s):
    s = re.sub(r"<!--.*?-->", "", s)
    s = re.sub(r"[\s，。；：、（）()【】\[\]-]", "", s)
    return s.lower()


def exact_master_line_match(claim, master_lines):
    """Only a whole normalized master line is deterministically supported.

    A longer edited claim containing a true master fragment may add an
    unsupported fact, so substring overlap is never proof of the whole line.
    Paraphrases remain review items until linked to more specific evidence.
    """
    normalized = norm(claim)
    return bool(normalized) and normalized in {norm(line) for line in master_lines if len(line.strip()) > 4}


def main():
    payload = json.load(sys.stdin)
    name = payload["master"]
    if not is_bare(name):
        raise ValueError("master must be a bare filename inside the vault directory")
    if not VAULT_DIR:
        raise ValueError("set CAREER_VAULT_DIR to your master-resume directory")
    master_path = os.path.join(VAULT_DIR, name)
    root_real = os.path.realpath(PROJECT_ROOT)
    draft_path = project_rel(payload["draft"])
    if not draft_path.startswith(root_real + os.sep):
        raise ValueError("traversal rejected: %s" % payload["draft"])

    draft = open(draft_path, encoding="utf8").read().splitlines()
    master_lines = [line for line in open(master_path, encoding="utf8").read().splitlines()
                    if len(line.strip()) > 4]

    claims = []
    for i, line in enumerate(draft, 1):
        stripped = re.sub(r"<!--.*?-->", "", line).strip()
        if len(stripped) < 6 or stripped.startswith(("#", ">")):
            continue
        linked = exact_master_line_match(stripped, master_lines)
        has_numbers = bool(NUM_RE.search(stripped))
        if linked and not has_numbers:
            risk, state = "LOW", "SUPPORTED"
        elif linked and has_numbers:
            risk, state = "MEDIUM", "SUPPORTED"
        else:
            risk = "HIGH" if has_numbers else "MEDIUM"
            state = "UNSUPPORTED"
        claims.append({"line": i, "claim": stripped[:120],
                       "isNewOrModified": ("ADDED" in line) or ("MODIFIED" in line),
                       "evidenceLinked": linked, "quantified": has_numbers,
                       "risk": risk, "state": state})
    unsupported = [c for c in claims if c["state"] == "UNSUPPORTED"]
    report = {"schema": "truth-guard-report@1",
              "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
              "draft": payload["draft"],
              "draftSha256": sha(draft_path), "masterSha256": sha(master_path),
              "components": {"claimExtraction": "标记行+实质行枚举",
                              "evidenceLinking": "仅完整归一化行精确匹配 master；改写须另行核证",
                              "riskClassification": "HIGH=量化无出处 / MEDIUM=无出处无量化 / LOW=master 出处"},
              "summary": {"totalClaims": len(claims),
                           "supported": len(claims) - len(unsupported),
                           "unsupported": len(unsupported),
                           "highRisk": sum(1 for c in unsupported if c["risk"] == "HIGH")},
              "claims": claims,
              "action": "UNSUPPORTED claims 需 Owner 逐条 ACCEPT(补真实证据)/REJECT(删除)后方可 publish"}
    out_name = payload["out"]
    if os.path.isabs(out_name) or ".." in out_name.replace("\\", "/").split("/"):
        raise ValueError("traversal rejected: %s" % out_name)
    report_path = os.path.join(root_real, os.path.normpath(out_name))
    if not report_path.startswith(root_real + os.sep):
        raise ValueError("traversal rejected: %s" % out_name)
    Path(report_path).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"report": payload["out"], "summary": report["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

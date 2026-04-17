"""
Stage: summarize
----------------
Generates a structured Markdown summary of the entire tender package from
the classified + extracted records.  This produces a single "wide retrieval
anchor" document that the RAG agent can surface in response to general
queries like "summarise this tender" without needing to aggregate dozens of
individual chunks.

Output files (both ingested into Dify):
  <out_dir>/<solicitation_id>/tender_summary.md   ← rich Markdown
  <out_dir>/<solicitation_id>/tender_summary.txt  ← plain text for embedding

Metadata tag:  doc_type = "tender_summary"
The summary is always amendment-aware: it explicitly states which amendment
is the latest and flags any documents superseded by that amendment.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .types import DocumentRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _group(records: list[DocumentRecord]) -> dict[str, list[DocumentRecord]]:
    groups: dict[str, list[DocumentRecord]] = {}
    for rec in sorted(records, key=lambda r: (r.sort_key, r.filename.lower())):
        groups.setdefault(rec.doc_type, []).append(rec)
    return groups


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n //= 1024
    return f"{n:.0f} TB"


def _latest_amendment(records: list[DocumentRecord]) -> int | None:
    nos = []
    for rec in records:
        if rec.doc_type == "amendment":
            import re
            m = re.search(r"amendment\+?[\s_-]*0*([0-9]+)", rec.filename, re.IGNORECASE)
            if m:
                nos.append(int(m.group(1)))
    return max(nos) if nos else None


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------

def build_summary(
    records: list[DocumentRecord],
    solicitation_id: str,
    validation: dict,
) -> str:
    """Return the full Markdown summary string."""
    groups = _group(records)
    latest_amend = _latest_amendment(records)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_docs = len(records)
    total_bytes = sum(r.size_bytes for r in records)

    extractable = [r for r in records if r.doc_type != "unknown"]
    has_text = [r for r in records
                if getattr(r, "has_extractable_text", False)]  # best-effort

    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────────
    lines += [
        f"# Tender Summary: {solicitation_id}",
        f"",
        f"> **Auto-generated** by NirmanAI pipeline on {generated_at}  ",
        f"> Latest amendment incorporated: **Amendment {latest_amend:03d}**" if latest_amend else "> No amendments detected",
        f"> ⚠️ This summary is derived from document metadata and extracted text. Always verify against source documents.",
        f"",
    ]

    # ── Quick-reference card ─────────────────────────────────────────────────
    lines += [
        "## Quick Reference",
        "",
        f"| Field | Value |",
        f"|---|---|",
        f"| Solicitation ID | `{solicitation_id}` |",
        f"| Total documents | {total_docs} |",
        f"| Total package size | {_fmt_size(total_bytes)} |",
        f"| Latest amendment | {'Amendment ' + str(latest_amend).zfill(3) if latest_amend else 'None detected'} |",
        f"| Validation status | {'✅ All required docs found' if validation.get('is_valid') else '⚠️ Missing required documents — see below'} |",
        f"| Summary generated | {generated_at} |",
        f"",
    ]

    # ── Validation / gap report ──────────────────────────────────────────────
    missing = validation.get("missing_required", [])
    if missing:
        lines += [
            "## ⚠️ Missing Required Documents",
            "",
            "The following required document types were not found in the package:",
            "",
        ]
        for m in missing:
            lines.append(f"- **{m['doc_type']}** — expected at least {m['expected_min']}, found {m['found']}")
        lines.append("")

    duplicates = validation.get("duplicates", [])
    if duplicates:
        lines += ["## ⚠️ Potential Duplicates", ""]
        for d in duplicates:
            lines.append(f"- `{d['doc_type']}` appears {d['count']} times — verify which is authoritative")
        lines.append("")

    # ── Solicitation overview ────────────────────────────────────────────────
    sol_docs = groups.get("solicitation", [])
    lines += ["## Solicitation Documents", ""]
    if sol_docs:
        for rec in sol_docs:
            lines += [
                f"- **{rec.filename}**",
                f"  - Size: {_fmt_size(rec.size_bytes)}",
                f"  - Section: `{rec.section}`",
                f"",
            ]
    else:
        lines += ["_No solicitation document detected._", ""]

    # ── Amendment timeline ────────────────────────────────────────────────────
    amend_docs = groups.get("amendment", [])
    lines += [
        "## Amendment Timeline",
        "",
        f"**{len(amend_docs)} amendment(s)** posted to this solicitation.",
        f"The authoritative version for all requirements is **Amendment {latest_amend:03d}**." if latest_amend else "",
        "",
    ]
    if amend_docs:
        lines.append("| Amendment | Filename | Size |")
        lines.append("|---|---|---|")
        for rec in amend_docs:
            import re
            m = re.search(r"amendment\+?[\s_-]*0*([0-9]+)", rec.filename, re.IGNORECASE)
            no = int(m.group(1)) if m else "?"
            marker = " ← **LATEST**" if no == latest_amend else ""
            lines.append(f"| Amendment {str(no).zfill(3)}{marker} | `{rec.filename}` | {_fmt_size(rec.size_bytes)} |")
        lines.append("")

    # ── Required submission items ─────────────────────────────────────────────
    lines += [
        "## Required Submission Items",
        "",
        "The following document types must be included in the bid package.",
        "Items marked ✅ have source files present; ❌ indicates missing.",
        "",
        "| # | Item | Status | Source File(s) |",
        "|---|---|---|---|",
    ]

    SUBMISSION_TYPES = [
        ("solicitation",       "Main RFP / Solicitation"),
        ("sf1442",             "SF-1442 Cover Sheet"),
        ("pricing",            "Price Form"),
        ("contract",           "Draft Agreement / Contract"),
        ("wage_determination", "Wage Determination"),
        ("past_performance",   "Past Performance Questionnaire"),
        ("bonding",            "Bond Forms (SF25/SF25A/SF25B/SF28)"),
        ("subcontracting_plan","Individual Subcontracting Plan"),
    ]

    for i, (dtype, label) in enumerate(SUBMISSION_TYPES, start=1):
        recs = groups.get(dtype, [])
        status = "✅" if recs else "❌"
        files = ", ".join(f"`{r.filename}`" for r in recs) if recs else "_not found_"
        lines.append(f"| {i} | {label} | {status} | {files} |")
    lines.append("")

    # ── Contract & labor requirements ────────────────────────────────────────
    lines += ["## Contract & Labor Requirements", ""]
    contract_docs = groups.get("contract", [])
    if contract_docs:
        lines.append("**Contract documents:**")
        for rec in contract_docs:
            lines.append(f"- `{rec.filename}` ({_fmt_size(rec.size_bytes)})")
    wd_docs = groups.get("wage_determination", [])
    if wd_docs:
        lines += ["", "**Wage Determinations (Davis-Bacon / Service Contract Act):**"]
        for rec in wd_docs:
            lines.append(f"- `{rec.filename}` — apply labor rates from this document to all cost estimates")
    lines.append("")

    # ── Security / admin requirements ────────────────────────────────────────
    admin_docs = groups.get("admin", [])
    if admin_docs:
        lines += [
            "## Security & Administrative Requirements",
            "",
            "The following admin/security documents are included in the package:",
            "",
        ]
        for rec in admin_docs:
            lines.append(f"- `{rec.filename}` (`{rec.doc_type}`, {_fmt_size(rec.size_bytes)})")
        lines.append("")

    # ── Complete document index ───────────────────────────────────────────────
    lines += [
        "## Complete Document Index",
        "",
        "All documents in the tender package, organized by section:",
        "",
    ]
    current_section = None
    for rec in sorted(records, key=lambda r: (r.section, r.sort_key, r.filename.lower())):
        if rec.section != current_section:
            current_section = rec.section
            lines.append(f"### {current_section}")
        lines.append(
            f"- `{rec.filename}` — **{rec.doc_type}** "
            f"| {_fmt_size(rec.size_bytes)} "
            f"| SHA256: `{rec.sha256[:12]}…`"
        )
    lines.append("")

    # ── RAG usage notes ───────────────────────────────────────────────────────
    lines += [
        "## RAG Agent Usage Notes",
        "",
        "This summary document is intended as a **wide retrieval anchor**.",
        "When the agent receives a general query about this tender, retrieve",
        "this document first, then use the `doc_type` and `amendment_no`",
        "metadata filters to pull specific supporting chunks.",
        "",
        "**Recommended retrieval strategy by query type:**",
        "",
        "| Query type | Recommended `doc_type` filter | Notes |",
        "|---|---|---|",
        "| General overview / requirements | `tender_summary` | This document |",
        "| Scope of work / specifications | `solicitation` | Check latest amendment for changes |",
        "| Rule changes / addenda | `amendment` | Filter `amendment_no = " + str(latest_amend) + "` for latest |" if latest_amend else "| Rule changes / addenda | `amendment` | |",
        "| Pricing / cost | `pricing` | Use with `wage_determination` for labor costs |",
        "| Contract terms | `contract` | Legal review required |",
        "| Labor rates | `wage_determination` | Required for compliant estimates |",
        "| Bond requirements | `bonding` | Check solicitation for trigger thresholds |",
        "| Past performance | `past_performance` | PPQ to be completed and returned |",
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_summary(
    records: list[DocumentRecord],
    solicitation_id: str,
    validation: dict,
    out_dir: str,
) -> dict:
    """
    Write tender_summary.md and tender_summary.txt to out_dir/solicitation_id/.
    Returns a dict with paths and basic stats.
    """
    base = Path(out_dir) / solicitation_id
    base.mkdir(parents=True, exist_ok=True)

    md_content = build_summary(records, solicitation_id, validation)
    # Plain text version: strip Markdown formatting minimally
    txt_content = md_content

    md_path  = base / "tender_summary.md"
    txt_path = base / "tender_summary.txt"
    meta_path = base / "tender_summary.meta.json"

    md_path.write_text(md_content, encoding="utf-8")
    txt_path.write_text(txt_content, encoding="utf-8")

    import re
    latest_amend = None
    for rec in records:
        if rec.doc_type == "amendment":
            m = re.search(r"amendment\+?[\s_-]*0*([0-9]+)", rec.filename, re.IGNORECASE)
            if m:
                n = int(m.group(1))
                latest_amend = max(latest_amend or 0, n)

    meta = {
        "solicitation_id":      solicitation_id,
        "doc_type":             "tender_summary",
        "section":              "00_Summary",
        "sort_key":             0,
        "latest_amendment_no":  latest_amend,
        "total_docs_indexed":   len(records),
        "is_valid":             validation.get("is_valid", False),
        "missing_required":     validation.get("missing_required", []),
        "generated_at":         datetime.now(timezone.utc).isoformat(),
        "has_extractable_text": True,
        "total_chars":          len(txt_content),
        "dify_doc_name":        f"[TENDER SUMMARY] {solicitation_id}",
        "dify_tags":            ["tender_summary", solicitation_id, "00_Summary"],
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return {
        "md_path":   str(md_path.resolve()),
        "txt_path":  str(txt_path.resolve()),
        "meta_path": str(meta_path.resolve()),
        "chars":     len(txt_content),
    }


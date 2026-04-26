import re

from .types import DocumentRecord


# ---------------------------------------------------------------------------
# doc_type → (section, sort_key) mapping used by BOTH filename and content paths
# ---------------------------------------------------------------------------
DOC_TYPE_SECTION: dict[str, tuple[str, int]] = {
    "solicitation":        ("01_Solicitation",   10),
    "amendment":           ("02_Amendments",     20),
    "sf1442":              ("03_Forms",          30),
    "pricing":             ("04_Pricing",        40),
    "contract":            ("05_Contract",       50),
    "wage_determination":  ("06_Labor",          60),
    "past_performance":    ("07_PastPerformance", 70),
    "bonding":             ("08_Bonding",        80),
    "subcontracting_plan": ("09_Subcontracting", 90),
    "admin":               ("10_Admin",         100),
    "drawings":            ("11_Drawings",      110),
    "unknown":             ("99_Appendix",      999),
}


# ---------------------------------------------------------------------------
# Classification rules  (pattern, doc_type, section, base_sort_key)
#
# Each filename (lowercased) is tested against patterns in order; first match wins.
# Patterns are written to handle both verbose names ("Solicitation+RHC+LPOE+...")
# and abbreviated names ("Sol_140A0126Q0028", "Sol_..._Amd_0001", etc.)
# ---------------------------------------------------------------------------
RULES: list[tuple[str, str, str, int]] = [
    # ── Amendments ───────────────────────────────────────────────────────────
    # Must come BEFORE solicitation so "Sol_..._Amd_0001" is caught as amendment.
    # Matches: Amendment+001, _Amd_0001, -amend-2, amd001, amendment_3
    # Also catches VA/DoD-style solicitation-id numbered suffixes: {ID}+0001, {ID}+0002.pdf
    # NOTE: bare solicitation IDs (no suffix number) are excluded so they fall through to solicitation.
    (r"[\b_\-+]amd[\b_\-+0-9]|amendment|[\b_\-+]amend[\b_\-+0-9]"
     r"|[a-z0-9]{7,}[+\-_]0*[1-9]\d{0,3}(?:\.\w+)?$",
     "amendment", "02_Amendments", 20),

    # ── Pricing / Cost ── (before solicitation to catch "RFP+Price+Form") ────
    (r"price[\s+_\-]*form|pricing|cost[\s+_\-]*form|bill.of.materials|\bbom\b|schedule.of.values"
     r"|bid.schedule|bid.quantity|quantities|division.cost|cost.breakdown",
     "pricing", "04_Pricing", 40),

    # ── Solicitation / RFP / RFQ ─────────────────────────────────────────────
    # Matches: Solicitation, Sol_, rfp, rfq, synopsis, project manual (VA construction)
    # Also: Specifications (standalone spec books are the solicitation body)
    (r"solicitation|(?:^|[_\-+])sol(?:[_\-+]|$)|\brfp\b|\brfq\b|synopsis|project.manual"
     r"|(?:^|[_\-+])spec(?:ification)?s?(?:[_\-+]|$)|specification",
     "solicitation", "01_Solicitation", 10),

    # ── Scope / Statement of Work ─────────────────────────────────────────────
    (r"statement.of.work|[\b_\-+]sow[\b_\-+]|scope.of.work|performance.work.statement|[\b_\-+]pws[\b_\-+]",
     "solicitation", "01_Solicitation", 11),

    # ── Bare solicitation ID (e.g. 36C24726R0083.docx — no numeric suffix) ──
    # A filename that IS just an alphanumeric solicitation-style ID (no +NNN suffix)
    (r"^[0-9]{2,3}[a-z][a-z0-9]{4,}[a-z][0-9]{4}(?:\.\w+)?$",
     "solicitation", "01_Solicitation", 12),

    # ── Standard Forms ───────────────────────────────────────────────────────
    (r"1442|sf1442|sf-1442",                            "sf1442",              "03_Forms",           30),
    (r"\bsf.?33\b|\bsf.?26\b|\bsf.?30\b",              "sf1442",              "03_Forms",           31),

    # ── Contract / Agreement ─────────────────────────────────────────────────
    (r"agreement|contract|teaming|nda|proprietary",     "contract",            "05_Contract",        50),

    # ── Wage Determinations ──────────────────────────────────────────────────
    (r"\bwd\b|wage.det|wage.rat|wage.rate|sca_wd|davis.bacon|\bdba\b|construction.wage",
     "wage_determination",  "06_Labor",           60),

    # ── Past Performance ─────────────────────────────────────────────────────
    (r"past.performance|ppq|past\+performance",          "past_performance",    "07_PastPerformance", 70),

    # ── Bonding ──────────────────────────────────────────────────────────────
    (r"sf.?25|sf.?28|\bbond\b|payment.bond|performance.bond",
     "bonding", "08_Bonding", 80),

    # ── Subcontracting ───────────────────────────────────────────────────────
    (r"subk|subcontract",                               "subcontracting_plan", "09_Subcontracting",  90),

    # ── Drawings ─────────────────────────────────────────────────────────────
    (r"drawing|floor.plan|site.plan|blueprint",
     "drawings", "11_Drawings", 110),

    # ── Admin / Forms / Representations ─────────────────────────────────────
    # Covers: vetting, site visit/walk sign-in, Q&A responses, risk assessments,
    # certifications, geotechnical reports, RFI forms, brand-name justifications,
    # tradeoff instructions, project information sheets
    (r"vetting|gaca|rsvp|attendance|site.walk|site.visit|sign.in|conference"
     r"|representation|certif|iee|far_|dfar|gsa\d"
     r"|risk.assess|technical.questions|questions.*responses|q.a.response"
     r"|geotech|geotechnical|\brfi\b|brand.name|justification|tradeoff|con.100"
     r"|project.information.sheet|instructions.*tradeoff"
     r"|experience.modif|emr|notice.of.limit|invoic|invoice",
     "admin", "10_Admin", 100),
]


def _amendment_num(name: str) -> int:
    """Extract amendment number from various naming conventions."""
    # Matches: Amendment+001, _Amd_0001, amd001, amendment_3, -amend-02
    # Also: {SOL_ID}+0001 VA-style numbered suffix
    m = re.search(r"(?:amendment|amend|amd)[+\s_\-]*0*([0-9]+)", name, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    # VA-style: trailing +NNNN or _NNNN
    m2 = re.search(r"[+\-_]0*([0-9]{1,4})$", name)
    if m2:
        return int(m2.group(1))
    return 999


def classify(records: list[DocumentRecord]) -> list[DocumentRecord]:
    for rec in records:
        name = rec.filename.lower()
        rec.doc_type = "unknown"
        rec.section = "99_Appendix"
        rec.sort_key = 999

        for pattern, doc_type, section, base_sort in RULES:
            if re.search(pattern, name):
                rec.doc_type = doc_type
                rec.section = section
                rec.sort_key = base_sort
                rec.classification_source = "filename"
                break

        if rec.doc_type == "amendment":
            rec.sort_key = 20 + _amendment_num(name)
    return records


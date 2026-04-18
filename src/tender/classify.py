import re

from .types import DocumentRecord


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
    (r"[\b_\-+]amd[\b_\-+0-9]|amendment|[\b_\-+]amend[\b_\-+0-9]",
     "amendment", "02_Amendments", 20),

    # ── Pricing / Cost ── (before solicitation to catch "RFP+Price+Form") ────
    (r"price[\s+_\-]*form|pricing|cost[\s+_\-]*form|bill.of.materials|\bbom\b|schedule.of.values",
     "pricing", "04_Pricing", 40),

    # ── Solicitation / RFP / RFQ ─────────────────────────────────────────────
    # Matches: Solicitation, Sol_, rfp, rfq, synopsis
    # Use word-boundary anchor on "sol" to avoid matching "solicitation" mid-word
    # when the pricing rule hasn't fired (pricing rule runs after this).
    (r"solicitation|(?:^|[_\-+])sol(?:[_\-+]|$)|\brfp\b|\brfq\b|synopsis",
     "solicitation", "01_Solicitation", 10),

    # ── Scope / Statement of Work ─────────────────────────────────────────────
    # Treated as part of the solicitation section
    (r"statement.of.work|[\b_\-+]sow[\b_\-+]|scope.of.work|performance.work.statement|[\b_\-+]pws[\b_\-+]",
     "solicitation", "01_Solicitation", 11),

    # ── Standard Forms ───────────────────────────────────────────────────────
    (r"1442|sf1442|sf-1442",                            "sf1442",              "03_Forms",           30),
    (r"\bsf.?33\b|\bsf.?26\b|\bsf.?30\b",              "sf1442",              "03_Forms",           31),


    # ── Contract / Agreement ─────────────────────────────────────────────────
    (r"agreement|contract|teaming|nda|proprietary",     "contract",            "05_Contract",        50),

    # ── Wage Determinations ──────────────────────────────────────────────────
    (r"\bwd\b|wage.det|sca_wd|davis.bacon|\bdba\b",     "wage_determination",  "06_Labor",           60),

    # ── Past Performance ─────────────────────────────────────────────────────
    (r"past.performance|ppq|past\+performance",          "past_performance",    "07_PastPerformance", 70),

    # ── Bonding ──────────────────────────────────────────────────────────────
    (r"sf.?25|sf.?28|\bbond\b|payment.bond|performance.bond",
     "bonding", "08_Bonding", 80),

    # ── Subcontracting ───────────────────────────────────────────────────────
    (r"subk|subcontract",                               "subcontracting_plan", "09_Subcontracting",  90),

    # ── Admin / Forms / Representations ─────────────────────────────────────
    (r"vetting|gaca|rsvp|attendance|site.walk|conference|representation|certif|iee|far_|dfar|gsa\d",
     "admin", "10_Admin", 100),
]


def _amendment_num(name: str) -> int:
    """Extract amendment number from various naming conventions."""
    # Matches: Amendment+001, _Amd_0001, amd001, amendment_3, -amend-02
    m = re.search(r"(?:amendment|amend|amd)[+\s_\-]*0*([0-9]+)", name, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
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


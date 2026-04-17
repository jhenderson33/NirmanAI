import re

from .types import DocumentRecord


RULES: list[tuple[str, str, str, int]] = [
    (r"solicitation", "solicitation", "01_Solicitation", 10),
    # Match "Amendment+001" etc. but NOT filenames that merely reference an amendment (e.g. RSVP forms)
    (r"^amendment[\s+_-]", "amendment", "02_Amendments", 20),
    (r"1442|sf1442", "sf1442", "03_Forms", 30),
    (r"price[\s+_]*form|pricing|cost", "pricing", "04_Pricing", 40),
    (r"agreement|contract", "contract", "05_Contract", 50),
    (r"wd|wage", "wage_determination", "06_Labor", 60),
    (r"past\+performance|past\s*performance|ppq", "past_performance", "07_PastPerformance", 70),
    (r"sf25|sf25a|sf25b|sf28|bond", "bonding", "08_Bonding", 80),
    (r"subk|subcontract", "subcontracting_plan", "09_Subcontracting", 90),
    (r"vetting|gaca|rsvp|attendance|site\+walk|conference", "admin", "10_Admin", 100),
]


def _amendment_num(name: str) -> int:
    m = re.search(r"amendment\+?\s*0*([0-9]+)", name, flags=re.IGNORECASE)
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
                break

        if rec.doc_type == "amendment":
            rec.sort_key = 20 + _amendment_num(name)
    return records



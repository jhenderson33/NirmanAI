from collections import Counter

from .types import DocumentRecord


def validate(records: list[DocumentRecord], required_rules: list[dict]) -> dict:
    counts = Counter(r.doc_type for r in records)
    missing: list[dict] = []

    for rule in required_rules:
        doc_type = rule.get("doc_type", "")
        min_count = int(rule.get("min_count", 1))
        if counts.get(doc_type, 0) < min_count:
            missing.append(
                {
                    "doc_type": doc_type,
                    "expected_min": min_count,
                    "found": counts.get(doc_type, 0),
                }
            )

    duplicates = [
        {"doc_type": dt, "count": c}
        for dt, c in counts.items()
        if c > 1 and dt in {"solicitation", "sf1442", "pricing"}
    ]

    return {
        "counts": dict(counts),
        "missing_required": missing,
        "duplicates": duplicates,
        "is_valid": len(missing) == 0,
    }


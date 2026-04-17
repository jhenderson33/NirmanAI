from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class DocumentRecord:
    rel_path: str
    abs_path: str
    filename: str
    ext: str
    size_bytes: int
    sha256: str
    doc_type: str = "unknown"
    section: str = "99_Appendix"
    sort_key: int = 999
    rendered_pdf: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


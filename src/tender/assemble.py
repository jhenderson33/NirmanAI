from pathlib import Path

from .types import DocumentRecord


try:
    from pypdf import PdfMerger  # type: ignore
except Exception:  # pragma: no cover
    PdfMerger = None

try:
    from pypdf import PdfWriter  # type: ignore
except Exception:  # pragma: no cover
    PdfWriter = None


def _sort_key(rec: DocumentRecord) -> tuple:
    return (rec.section, rec.sort_key, rec.filename.lower())


def assemble_binder(records: list[DocumentRecord], binder_pdf_path: str, index_md_path: str) -> dict:
    pdf_docs = [r for r in records if r.rendered_pdf]
    pdf_docs.sort(key=_sort_key)

    index_lines = ["# Tender Binder Index", ""]
    current_section = None
    for i, rec in enumerate(pdf_docs, start=1):
        if rec.section != current_section:
            current_section = rec.section
            index_lines.append(f"## {current_section}")
        index_lines.append(f"{i}. `{rec.filename}` ({rec.doc_type})")

    Path(index_md_path).parent.mkdir(parents=True, exist_ok=True)
    Path(index_md_path).write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    if PdfMerger is None and PdfWriter is None:
        return {
            "binder_created": False,
            "reason": "pypdf is not installed",
            "pdfs_included": len(pdf_docs),
        }

    out = Path(binder_pdf_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if PdfMerger is not None:
        merger = PdfMerger()
        for rec in pdf_docs:
            merger.append(rec.rendered_pdf)
        merger.write(str(out))
        merger.close()
    else:
        writer = PdfWriter()
        for rec in pdf_docs:
            writer.append(rec.rendered_pdf)
        with out.open("wb") as f:
            writer.write(f)

    return {
        "binder_created": True,
        "binder_pdf": str(out.resolve()),
        "pdfs_included": len(pdf_docs),
    }


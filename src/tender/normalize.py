import shutil
import subprocess
from pathlib import Path

from .types import DocumentRecord


OFFICE_EXTS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}


def _convert_with_soffice(input_path: Path, output_dir: Path) -> Path | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "soffice",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(input_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    candidate = output_dir / f"{input_path.stem}.pdf"
    return candidate if candidate.exists() else None


def normalize_to_pdf(records: list[DocumentRecord], render_dir: str, convert_office_docs: bool) -> list[DocumentRecord]:
    render_path = Path(render_dir)
    render_path.mkdir(parents=True, exist_ok=True)

    for rec in records:
        src = Path(rec.abs_path)
        rel_parent = Path(rec.rel_path).parent
        dst_parent = render_path / rel_parent
        dst_parent.mkdir(parents=True, exist_ok=True)

        if rec.ext == ".pdf":
            # Keep source PDF directly for assembly.
            rec.rendered_pdf = rec.abs_path
            continue

        if rec.ext in OFFICE_EXTS and convert_office_docs:
            converted = _convert_with_soffice(src, dst_parent)
            if converted:
                rec.rendered_pdf = str(converted.resolve())
                continue

        # No conversion available; keep blank so assembler can skip gracefully.
        rec.rendered_pdf = ""

    return records


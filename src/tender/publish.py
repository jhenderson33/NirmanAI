import shutil
from pathlib import Path

from .types import DocumentRecord
from .utils import write_json


def publish(records: list[DocumentRecord], validation: dict, assembly: dict, out_dir: str, solicitation_id: str) -> dict:
    base = Path(out_dir) / solicitation_id
    pack = base / "submission_pack"
    pack.mkdir(parents=True, exist_ok=True)

    copied = 0
    for rec in records:
        section_dir = pack / rec.section
        section_dir.mkdir(parents=True, exist_ok=True)
        dst = section_dir / rec.filename
        if dst.exists():
            dst = section_dir / f"dup_{rec.filename}"
        shutil.copy2(rec.abs_path, dst)
        copied += 1

    manifest = {
        "solicitation_id": solicitation_id,
        "documents": [r.to_dict() for r in records],
        "validation": validation,
        "assembly": assembly,
        "submission_pack": str(pack.resolve()),
        "documents_copied": copied,
    }

    write_json(base / "binder_manifest.json", manifest)
    return manifest


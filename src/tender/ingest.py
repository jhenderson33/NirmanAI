from pathlib import Path

from .types import DocumentRecord
from .utils import sha256_file


def ingest(source_dir: str) -> list[DocumentRecord]:
    src = Path(source_dir)
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")

    docs: list[DocumentRecord] = []
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src).as_posix()
        docs.append(
            DocumentRecord(
                rel_path=rel,
                abs_path=str(path.resolve()),
                filename=path.name,
                ext=path.suffix.lower(),
                size_bytes=path.stat().st_size,
                sha256=sha256_file(path),
            )
        )
    return docs


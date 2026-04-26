from pathlib import Path

from .types import DocumentRecord
from .utils import sha256_file


# Extensions that are not useful source documents (metadata, lock files, etc.)
_SKIP_EXTENSIONS = {".json", ".tmp", ".ds_store"}
# Filename prefixes to skip (Office temp/lock files)
_SKIP_PREFIXES = ("~$",)


def ingest(source_dir: str) -> list[DocumentRecord]:
    src = Path(source_dir)
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")

    docs: list[DocumentRecord] = []
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in _SKIP_EXTENSIONS:
            continue
        if any(path.name.startswith(p) for p in _SKIP_PREFIXES):
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


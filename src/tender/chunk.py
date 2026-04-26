"""
Stage: chunk
------------
Splits extracted text files that exceed Dify's 400,000-character per-document
limit into numbered part files.

For a document  `MySol.txt`  with 950,000 chars the output is:
  MySol.part001.txt          (~400 000 chars, split at a newline boundary)
  MySol.part001.meta.json
  MySol.part002.txt
  MySol.part002.meta.json
  MySol.part003.txt
  MySol.part003.meta.json

The original `MySol.txt` is left in place (it is still useful for local
inspection) but is NOT intended for Dify upload when chunks exist.
The parent meta at `MySol.meta.json` gains two new fields:
  "is_chunked": true
  "chunks": [ {"part": 1, "txt_file": "...", "meta_file": "...", "chars": N}, ... ]
"""
from __future__ import annotations

import json
from pathlib import Path

DIFY_CHAR_LIMIT = 400_000


def _split_at_boundary(text: str, max_chars: int) -> list[str]:
    """
    Split *text* into segments of at most *max_chars* characters,
    preferring to break at a newline boundary rather than mid-line.
    """
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + max_chars, length)
        if end < length:
            # Try to find a newline to break at cleanly
            newline_pos = text.rfind("\n", start, end)
            if newline_pos > start:
                end = newline_pos + 1  # include the newline in this chunk
        chunks.append(text[start:end])
        start = end
    return chunks


def maybe_chunk(
    txt_path: Path,
    meta_path: Path,
    base_meta: dict,
) -> list[dict]:
    """
    If the text in *txt_path* exceeds DIFY_CHAR_LIMIT, write numbered part
    files alongside it and update the parent meta file with chunk info.

    Returns a list of chunk meta dicts (empty if no chunking was needed).
    """
    text = txt_path.read_text(encoding="utf-8")
    if len(text) <= DIFY_CHAR_LIMIT:
        return []

    parts = _split_at_boundary(text, DIFY_CHAR_LIMIT)
    stem = txt_path.stem          # e.g.  "Volume_1_Specs"
    parent_dir = txt_path.parent
    total_parts = len(parts)

    chunk_metas: list[dict] = []

    for i, chunk_text in enumerate(parts, start=1):
        part_label = f"part{i:03d}"
        part_stem  = f"{stem}.{part_label}"
        part_txt   = parent_dir / f"{part_stem}.txt"
        part_meta_path = parent_dir / f"{part_stem}.meta.json"

        part_txt.write_text(chunk_text, encoding="utf-8")

        part_meta: dict = {
            **base_meta,
            # Override the fields that differ per-chunk
            "filename":      f"{part_stem}.txt",
            "doc_type":      base_meta.get("doc_type", "unknown"),
            "total_chars":   len(chunk_text),
            "has_extractable_text": len(chunk_text.strip()) > 50,
            # Chunk-specific fields
            "is_chunk":      True,
            "chunk_part":    i,
            "chunk_total":   total_parts,
            "chunk_of":      txt_path.name,
            "dify_doc_name": f"{base_meta.get('dify_doc_name', stem)} [{part_label}/{total_parts}]",
            "dify_tags":     base_meta.get("dify_tags", []) + [part_label],
        }

        part_meta_path.write_text(json.dumps(part_meta, indent=2), encoding="utf-8")

        chunk_metas.append({
            "part":      i,
            "txt_file":  str(part_txt.name),
            "meta_file": str(part_meta_path.name),
            "chars":     len(chunk_text),
        })

    # Patch the parent meta with chunk info (in-place update)
    base_meta["is_chunked"]  = True
    base_meta["chunk_count"] = total_parts
    base_meta["chunks"]      = chunk_metas
    meta_path.write_text(json.dumps(base_meta, indent=2), encoding="utf-8")

    return chunk_metas


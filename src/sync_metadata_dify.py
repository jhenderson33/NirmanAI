"""
sync_metadata_dify.py — Sync metadata from dist/extracted onto existing Dify documents.

What it does
------------
1.  Lists every document already in the target Dify dataset.
2.  Walks dist_dir/extracted/**/*.meta.json (and tender_summary.meta.json).
3.  Matches Dify document names to local meta files by normalising both to
    a stem (strip extension, lower-case, collapse whitespace).
4.  Ensures the required metadata-schema fields exist on the dataset.
5.  Bulk-patches every matched document with its structured metadata.
6.  Prints a report of matched, skipped, and unmatched documents.

Usage
-----
    python src/sync_metadata_dify.py --dist-dir dist/sample --dataset-id <id>

    --dist-dir    PATH   Required. Path to the pipeline output for one tender.
    --dataset-id  ID     Required. The Dify dataset to update.
    --base-url    URL    Dify API root (default: $DIFY_BASE_URL or
                         https://api.dify.ai/v1)
    --dry-run            Print the match plan without making any API calls.

Environment
-----------
    DIFY_API_KEY  — Required.
    DIFY_BASE_URL — Optional.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync pipeline metadata onto existing Dify documents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dist-dir",   required=True,  help="Path to dist/<solicitation_id>/")
    parser.add_argument("--dataset-id", required=True,  help="Dify dataset ID to update")
    parser.add_argument("--base-url",   default=None,   help="Dify API base URL")
    parser.add_argument("--dry-run",    action="store_true", help="Print plan, make no API calls")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Dify API client (minimal — only what we need)
# ---------------------------------------------------------------------------

class DifyClient:
    def __init__(self, api_key: str, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.headers  = {"Authorization": f"Bearer {api_key}"}

    def _get(self, path: str, params: dict | None = None) -> dict:
        r = requests.get(f"{self.base_url}{path}", headers=self.headers,
                         params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        r = requests.post(
            f"{self.base_url}{path}",
            headers={**self.headers, "Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def list_documents(self, dataset_id: str) -> list[dict]:
        """Return all documents in the dataset (handles pagination)."""
        docs: list[dict] = []
        page = 1
        while True:
            data = self._get(f"/datasets/{dataset_id}/documents",
                             {"page": page, "limit": 100})
            docs.extend(data.get("data", []))
            if not data.get("has_more"):
                break
            page += 1
        return docs

    def list_metadata_fields(self, dataset_id: str) -> list[dict]:
        data = self._get(f"/datasets/{dataset_id}/metadata")
        return data.get("doc_metadata", [])

    def ensure_metadata_field(self, dataset_id: str, field_name: str,
                               field_type: str, existing: list[dict]) -> str:
        for f in existing:
            if f["name"] == field_name:
                return f["id"]
        data = self._post(f"/datasets/{dataset_id}/metadata",
                          {"type": field_type, "name": field_name})
        return data["id"]

    def bulk_set_metadata(self, dataset_id: str, operations: list[dict]) -> dict:
        body = {"operation_data": operations, "dataset_id": dataset_id}
        return self._post(f"/datasets/{dataset_id}/documents/metadata", body)


# ---------------------------------------------------------------------------
# Metadata schema (must match publish_dify.py)
# ---------------------------------------------------------------------------

METADATA_SCHEMA: list[tuple[str, str]] = [
    ("doc_type",              "string"),
    ("solicitation_id",       "string"),
    ("rag_strategy",          "string"),
    ("section",               "string"),
    ("classification_source", "string"),
    ("amendment_no",          "number"),
    ("is_latest_amendment",   "string"),
    ("total_pages",           "number"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise(name: str) -> str:
    """Strip extension, lower-case, collapse non-alphanumeric runs to a single space."""
    stem = Path(name).stem
    return re.sub(r"[^a-z0-9]+", " ", stem.lower()).strip()


def _load_meta_index(dist_dir: Path) -> dict[str, dict]:
    """
    Returns {normalised_stem: meta_dict} for every .meta.json found under
    dist_dir/extracted/ and for tender_summary.meta.json.
    """
    index: dict[str, dict] = {}

    extracted = dist_dir / "extracted"
    if extracted.exists():
        for meta_path in extracted.rglob("*.meta.json"):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            # Index by the pipeline-generated dify_doc_name (preferred) and
            # also the raw filename stem so we get two chances to match.
            for candidate in [
                meta.get("dify_doc_name", ""),
                meta.get("filename", ""),
                meta_path.stem.replace(".meta", ""),
            ]:
                key = _normalise(candidate)
                if key:
                    index[key] = meta

    # Tender summary
    summary_meta_path = dist_dir / "tender_summary.meta.json"
    if summary_meta_path.exists():
        meta = json.loads(summary_meta_path.read_text(encoding="utf-8"))
        for candidate in [meta.get("dify_doc_name", ""), "tender_summary",
                          "tender summary"]:
            key = _normalise(candidate)
            if key:
                index[key] = meta

    return index


def _val(meta: dict, key: str):
    v = meta.get(key)
    if key == "is_latest_amendment":
        return str(v).lower() if v is not None else "false"
    return v


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    api_key  = os.environ.get("DIFY_API_KEY")
    base_url = args.base_url or os.environ.get("DIFY_BASE_URL", "https://api.dify.ai/v1")

    if not api_key:
        print("❌  DIFY_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    dist_dir = Path(args.dist_dir).resolve()
    if not dist_dir.exists():
        print(f"❌  dist-dir not found: {dist_dir}", file=sys.stderr)
        sys.exit(1)

    dataset_id      = args.dataset_id
    solicitation_id = dist_dir.name

    print(f"\n{'='*60}")
    print(f"  Metadata Sync — {solicitation_id}")
    print(f"{'='*60}")
    print(f"  dataset id   : {dataset_id}")
    print(f"  dist dir     : {dist_dir}")
    print(f"  dry run      : {args.dry_run}\n")

    # ── Load local meta index ─────────────────────────────────────────────
    print("📂  Scanning local meta files …")
    meta_index = _load_meta_index(dist_dir)
    print(f"    {len(meta_index)} meta entries loaded\n")

    # ── List Dify documents ───────────────────────────────────────────────
    client = DifyClient(api_key, base_url)

    print("🔍  Fetching documents from Dify dataset …")
    dify_docs = client.list_documents(dataset_id)
    print(f"    {len(dify_docs)} document(s) found\n")

    # ── Match documents to meta ───────────────────────────────────────────
    matched:   list[dict] = []   # {document_id, dify_name, meta}
    unmatched: list[str]  = []   # dify document names with no local meta

    for doc in dify_docs:
        dify_name = doc.get("name", "")
        key = _normalise(dify_name)
        meta = meta_index.get(key)

        if meta:
            matched.append({"document_id": doc["id"], "dify_name": dify_name, "meta": meta})
        else:
            unmatched.append(dify_name)

    print(f"🔗  Match results:")
    print(f"    ✅ Matched   : {len(matched)}")
    print(f"    ❓ Unmatched : {len(unmatched)}")
    if unmatched:
        print("    Unmatched document names (no local meta found):")
        for name in unmatched:
            print(f"      — {name}")
    print()

    if args.dry_run:
        print("DRY RUN — would update metadata for:\n")
        for m in matched:
            meta = m["meta"]
            print(f"  {m['dify_name']}")
            print(f"    doc_type={meta.get('doc_type')}  "
                  f"section={meta.get('section')}  "
                  f"rag_strategy={meta.get('rag_strategy')}  "
                  f"pages={meta.get('total_pages')}")
        print("\nNo API calls made (--dry-run).")
        return

    if not matched:
        print("Nothing to update.")
        return

    # ── Ensure metadata schema ────────────────────────────────────────────
    print("🗂   Ensuring metadata schema fields …")
    existing_fields = client.list_metadata_fields(dataset_id)
    field_id_map: dict[str, str] = {}
    for field_name, field_type in METADATA_SCHEMA:
        fid = client.ensure_metadata_field(dataset_id, field_name, field_type, existing_fields)
        field_id_map[field_name] = fid
        if not any(f["name"] == field_name for f in existing_fields):
            existing_fields.append({"name": field_name, "id": fid, "type": field_type})
    print(f"    {len(field_id_map)} field(s) ready\n")

    # ── Build and send bulk metadata update ───────────────────────────────
    print(f"🏷   Updating metadata on {len(matched)} document(s) …\n")

    META_KEYS = [name for name, _ in METADATA_SCHEMA]
    operations = []
    for item in matched:
        meta_list = []
        for key in META_KEYS:
            val = _val(item["meta"], key)
            if val is not None:
                meta_list.append({"id": field_id_map[key], "name": key, "value": val})
        if meta_list:
            operations.append({"document_id": item["document_id"], "metadata_list": meta_list})

    errors: list[str] = []
    try:
        client.bulk_set_metadata(dataset_id, operations)
        print("    ✔  Metadata applied\n")
    except requests.exceptions.HTTPError as exc:
        print(f"    ⚠  Bulk update failed: {exc}")
        print(f"    Response body: {exc.response.text}\n")
        errors.append(str(exc))
    except Exception as exc:
        print(f"    ⚠  Bulk update failed: {exc}\n")
        errors.append(str(exc))

    # ── Summary ───────────────────────────────────────────────────────────
    print("=" * 60)
    print(f"  DONE")
    print(f"  Dataset    : {dataset_id}")
    print(f"  Updated    : {len(matched) if not errors else 0} / {len(matched)}")
    print(f"  Unmatched  : {len(unmatched)}")
    if errors:
        print(f"  Errors     : {len(errors)}")
        for e in errors:
            print(f"    • {e}")
    print("=" * 60)
    print(f"\n  Open in Dify: {base_url.replace('/v1','')}/datasets/{dataset_id}/documents\n")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()


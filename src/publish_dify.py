"""
publish_dify.py — Upload a processed tender to a Dify knowledge base.

What it does
------------
1.  Reads every  <dist_dir>/extracted/**/*.txt  +  *.meta.json  pair produced
    by the pipeline.
2.  Creates (or finds) a Dify dataset named after the solicitation ID.
3.  Ensures the required metadata-schema fields exist on that dataset.
4.  Uploads each .txt file as a Dify document (skipping reference-only docs
    unless --all is passed).
5.  Always uploads the  tender_summary.md  / tender_summary.txt  anchor doc.
6.  Bulk-patches every uploaded document with its structured metadata so Dify
    can filter on doc_type, rag_strategy, solicitation_id, etc.

Usage
-----
    python src/publish_dify.py --dist-dir dist/36C77626B0013 [options]

    --dist-dir   PATH   Required. Path to the pipeline output for one tender.
    --base-url   URL    Dify API root  (default: $DIFY_BASE_URL or
                        https://api.dify.ai/v1)
    --dataset-id ID     Skip dataset lookup/creation and push into this ID.
    --all               Also upload reference_only docs (drawings, unknowns).
    --dry-run           Print what would be uploaded without making API calls.
    --delay   SECS      Seconds to wait between document uploads (default 1).

Environment
-----------
    DIFY_API_KEY   — Required.  Your Dify knowledge-base API key.
    DIFY_BASE_URL  — Optional.  Override the API root URL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload a processed tender dist directory to Dify.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dist-dir",    required=True,  help="Path to dist/<solicitation_id>/")
    parser.add_argument("--base-url",    default=None,   help="Dify API base URL")
    parser.add_argument("--dataset-id",  default=None,   help="Use existing dataset instead of creating one")
    parser.add_argument("--all",         action="store_true", dest="include_all",
                        help="Include reference_only docs (drawings, unknowns)")
    parser.add_argument("--dry-run",     action="store_true", help="Print plan, make no API calls")
    parser.add_argument("--delay",       type=float, default=1.0,
                        help="Seconds between uploads (default 1)")
    parser.add_argument("--pipeline",    action="store_true",
                        help="Target a pipeline-configured dataset: upload via create-by-file "
                             "and defer all chunking/indexing settings to the pipeline config. "
                             "Use with --dataset-id.")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Dify API client
# ---------------------------------------------------------------------------

class DifyClient:
    def __init__(self, api_key: str, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.headers  = {"Authorization": f"Bearer {api_key}"}

    def _get(self, path: str, params: dict | None = None) -> dict:
        r = requests.get(f"{self.base_url}{path}", headers=self.headers, params=params, timeout=30)
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

    def _post_file(self, path: str, filename: str, text: str, extra_data: dict) -> dict:
        """Upload a document as a multipart text file."""
        files = {
            "file": (filename, text.encode("utf-8"), "text/plain"),
            **{k: (None, str(v)) for k, v in extra_data.items()},
        }
        r = requests.post(
            f"{self.base_url}{path}",
            headers=self.headers,   # no Content-Type — requests sets multipart boundary
            files=files,
            timeout=120,
        )
        r.raise_for_status()
        return r.json()

    # ── Datasets ────────────────────────────────────────────────────────────

    def find_dataset(self, name: str) -> str | None:
        """Return dataset_id if a dataset with this name already exists."""
        page = 1
        while True:
            data = self._get("/datasets", {"keyword": name, "page": page, "limit": 100})
            for ds in data.get("data", []):
                if ds["name"] == name:
                    return ds["id"]
            if not data.get("has_more"):
                return None
            page += 1

    def create_dataset(self, name: str, description: str = "") -> str:
        body = {
            "name":               name,
            "description":        description,
            "indexing_technique": "high_quality",
            "permission":         "only_me",
        }
        data = self._post("/datasets", body)
        return data["id"]

    def get_or_create_dataset(self, name: str, description: str = "") -> tuple[str, bool]:
        """Returns (dataset_id, created:bool)."""
        existing = self.find_dataset(name)
        if existing:
            return existing, False
        return self.create_dataset(name, description), True

    # ── Metadata schema ─────────────────────────────────────────────────────

    def list_metadata_fields(self, dataset_id: str) -> list[dict]:
        data = self._get(f"/datasets/{dataset_id}/metadata")
        return data.get("doc_metadata", [])

    def ensure_metadata_field(
        self, dataset_id: str, field_name: str, field_type: str,
        existing: list[dict],
    ) -> str:
        """Create a metadata field if it doesn't already exist. Returns its id."""
        for f in existing:
            if f["name"] == field_name:
                return f["id"]
        data = self._post(f"/datasets/{dataset_id}/metadata", {"type": field_type, "name": field_name})
        return data["id"]

    # ── Documents ───────────────────────────────────────────────────────────

    def upload_document(self, dataset_id: str, name: str, text: str,
                        pipeline_mode: bool = False) -> dict:
        """Upload a document by text (or file if pipeline_mode). Returns the document object."""
        stem = Path(name).stem if name.lower().endswith((".pdf", ".docx", ".xlsx", ".doc", ".xls")) else name
        safe_name = stem + ".txt"

        if pipeline_mode:
            # Send only the file — no process_rule or indexing_technique —
            # so Dify applies the pipeline's own configured settings.
            return self._upload_by_file(dataset_id, safe_name, text)
        else:
            body: dict = {
                "name":               safe_name,
                "text":               text,
                "indexing_technique": "high_quality",
                "process_rule":       {"mode": "automatic"},
            }
            data = self._post(f"/datasets/{dataset_id}/document/create-by-text", body)
            return data.get("document", data)

    def _upload_by_file(self, dataset_id: str, filename: str, text: str) -> dict:
        """Upload text as a .txt file via multipart. No process_rule is sent,
        so the dataset's pipeline configuration applies."""
        files = {
            "file": (filename, text.encode("utf-8"), "text/plain"),
        }
        r = requests.post(
            f"{self.base_url}/datasets/{dataset_id}/document/create-by-file",
            headers=self.headers,
            files=files,
            timeout=120,
        )
        r.raise_for_status()
        result = r.json()
        return result.get("document", result)

    def list_documents(self, dataset_id: str) -> list[dict]:
        """Return all documents in a dataset (handles pagination)."""
        docs: list[dict] = []
        page = 1
        while True:
            data = self._get(f"/datasets/{dataset_id}/documents", {"page": page, "limit": 100})
            docs.extend(data.get("data", []))
            if not data.get("has_more"):
                break
            page += 1
        return docs

    # ── Document metadata values ─────────────────────────────────────────────

    def bulk_set_metadata(
        self,
        dataset_id: str,
        operations: list[dict],  # [{"document_id": "...", "metadata_list": [{"id": "...", "value": ...}]}]
    ) -> dict:
        body = {"operation_data": operations, "dataset_id": dataset_id}
        return self._post(f"/datasets/{dataset_id}/documents/metadata", body)


# ---------------------------------------------------------------------------
# Metadata field schema — fields we want on every document
# ---------------------------------------------------------------------------

# (name, dify_type)   dify_type: "string" | "number" | "time" | "email" | "url"
METADATA_SCHEMA: list[tuple[str, str]] = [
    ("doc_type",              "string"),
    ("solicitation_id",       "string"),
    ("rag_strategy",          "string"),
    ("section",               "string"),
    ("classification_source", "string"),
    ("amendment_no",          "number"),
    ("is_latest_amendment",   "string"),   # "true" / "false" — Dify has no bool
    ("total_pages",           "number"),
]


# ---------------------------------------------------------------------------
# Discovery: find all uploadable documents in the dist directory
# ---------------------------------------------------------------------------

def _load_doc_pairs(dist_dir: Path, include_all: bool) -> list[dict]:
    """
    Walk dist_dir/extracted/**/*.txt, match with .meta.json sidecars,
    and also pick up tender_summary.md/.txt if present.
    Returns list of dicts with keys: txt_path, meta, name, skip_reason.
    """
    pairs: list[dict] = []
    extracted = dist_dir / "extracted"

    if extracted.exists():
        for txt_path in sorted(extracted.rglob("*.txt")):
            meta_path = txt_path.with_suffix(".meta.json")
            if not meta_path.exists():
                # No sidecar — include anyway with minimal meta
                pairs.append({
                    "txt_path":    txt_path,
                    "meta":        {"doc_type": "unknown", "rag_strategy": "reference_only"},
                    "name":        txt_path.stem,
                    "skip_reason": None if include_all else "no_meta",
                })
                continue

            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            rag  = meta.get("rag_strategy", "full")
            skip = None
            if rag == "reference_only" and not include_all:
                skip = f"rag_strategy=reference_only (use --all to include)"

            pairs.append({
                "txt_path":    txt_path,
                "meta":        meta,
                "name":        meta.get("dify_doc_name") or txt_path.stem,
                "skip_reason": skip,
            })

    # Always include the summary anchor (it's outside extracted/)
    for summary_name in ("tender_summary.md", "tender_summary.txt"):
        sp = dist_dir / summary_name
        if sp.exists():
            meta_path = dist_dir / "tender_summary.meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {
                "doc_type": "tender_summary", "rag_strategy": "full"
            }
            # Avoid duplicates if it somehow ended up in extracted/ too
            if not any(p["txt_path"] == sp for p in pairs):
                pairs.append({
                    "txt_path":    sp,
                    "meta":        meta,
                    "name":        meta.get("dify_doc_name") or "Tender Summary",
                    "skip_reason": None,
                })
            break

    return pairs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    # ── Resolve API credentials ───────────────────────────────────────────
    api_key  = os.environ.get("DIFY_API_KEY")
    base_url = args.base_url or os.environ.get("DIFY_BASE_URL", "https://api.dify.ai/v1")

    if not api_key:
        print("❌  DIFY_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    dist_dir = Path(args.dist_dir).resolve()
    if not dist_dir.exists():
        print(f"❌  dist-dir not found: {dist_dir}", file=sys.stderr)
        sys.exit(1)

    # Infer solicitation_id from the directory name
    solicitation_id = dist_dir.name
    dataset_name    = solicitation_id   # one KB per tender

    print(f"\n{'='*60}")
    print(f"  Dify Publisher — {solicitation_id}")
    print(f"{'='*60}")
    print(f"  API base     : {base_url}")
    print(f"  dist dir     : {dist_dir}")
    print(f"  include all  : {args.include_all}")
    print(f"  dry run      : {args.dry_run}")
    print(f"  pipeline mode: {args.pipeline}\n")

    # In pipeline mode, process_rule is intentionally omitted so Dify
    # applies the dataset's own configured pipeline settings.

    # ── Discover documents ────────────────────────────────────────────────
    pairs = _load_doc_pairs(dist_dir, args.include_all)
    to_upload = [p for p in pairs if p["skip_reason"] is None]
    skipped   = [p for p in pairs if p["skip_reason"] is not None]

    print(f"📄  Documents found     : {len(pairs)}")
    print(f"   ✅ To upload         : {len(to_upload)}")
    print(f"   ⏭  Skipped          : {len(skipped)}")
    if skipped:
        for p in skipped:
            print(f"       — {p['name']}  ({p['skip_reason']})")
    print()

    if args.dry_run:
        print("DRY RUN — the following would be uploaded:\n")
        for p in to_upload:
            meta = p["meta"]
            print(f"  [{meta.get('doc_type','?'):20s}] {p['name']}")
            print(f"    rag_strategy={meta.get('rag_strategy')}  "
                  f"section={meta.get('section')}  "
                  f"pages={meta.get('total_pages')}")
        print("\nNo API calls made (--dry-run).")
        return

    if not to_upload:
        print("Nothing to upload.")
        return

    # ── Connect to Dify ───────────────────────────────────────────────────
    client = DifyClient(api_key, base_url)

    # ── Find or create dataset ────────────────────────────────────────────
    if args.dataset_id:
        dataset_id = args.dataset_id
        print(f"📦  Using existing dataset : {dataset_id}\n")
    else:
        print(f"🔍  Looking up dataset '{dataset_name}' …")
        dataset_id, created = client.get_or_create_dataset(
            dataset_name,
            description=f"Tender package for solicitation {solicitation_id}",
        )
        verb = "Created" if created else "Found existing"
        print(f"    {verb} dataset: {dataset_id}\n")

    # ── Ensure metadata schema ────────────────────────────────────────────
    print("🗂   Ensuring metadata schema …")
    existing_fields = client.list_metadata_fields(dataset_id)
    field_id_map: dict[str, str] = {}    # field_name -> field_id
    for field_name, field_type in METADATA_SCHEMA:
        fid = client.ensure_metadata_field(dataset_id, field_name, field_type, existing_fields)
        field_id_map[field_name] = fid
        # Keep existing_fields fresh (avoid re-creating on repeated runs)
        if not any(f["name"] == field_name for f in existing_fields):
            existing_fields.append({"name": field_name, "id": fid, "type": field_type})
    print(f"    {len(field_id_map)} field(s) ready\n")

    # ── Upload documents ──────────────────────────────────────────────────
    print(f"⬆️   Uploading {len(to_upload)} document(s) …\n")
    uploaded: list[dict] = []   # {"document_id": ..., "meta": ...}
    errors:   list[str]  = []

    for idx, pair in enumerate(to_upload, start=1):
        name     = pair["name"]
        txt_path = pair["txt_path"]
        meta     = pair["meta"]

        print(f"  [{idx:>2}/{len(to_upload)}] {name}")

        try:
            text = txt_path.read_text(encoding="utf-8")
            doc  = client.upload_document(dataset_id, name, text,
                                          pipeline_mode=args.pipeline)
            doc_id = doc.get("id") or doc.get("document", {}).get("id")
            if not doc_id:
                raise ValueError(f"No document ID in response: {doc}")
            uploaded.append({"document_id": doc_id, "meta": meta})
            size_kb = txt_path.stat().st_size // 1024
            print(f"         ✔  id={doc_id}  ({size_kb} KB text)")
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            print(f"         ⚠  FAILED: {exc}")

        if idx < len(to_upload):
            time.sleep(args.delay)

    print()

    # ── Bulk-set metadata ─────────────────────────────────────────────────
    if uploaded:
        print("⏳  Waiting 60s for Dify to finish indexing …")
        time.sleep(60)
        print(f"🏷   Setting metadata on {len(uploaded)} document(s) …")

        META_KEYS = [name for name, _ in METADATA_SCHEMA]

        def _val(meta: dict, key: str):
            v = meta.get(key)
            if key == "is_latest_amendment":
                return str(v).lower() if v is not None else "false"
            return v

        operations = []
        for item in uploaded:
            meta_list = []
            for key in META_KEYS:
                val = _val(item["meta"], key)
                if val is not None:
                    meta_list.append({"id": field_id_map[key], "name": key, "value": val})
            if meta_list:
                operations.append({"document_id": item["document_id"], "metadata_list": meta_list})

        try:
            client.bulk_set_metadata(dataset_id, operations)
            print(f"    ✔  Metadata applied\n")
        except requests.exceptions.HTTPError as exc:
            print(f"    ⚠  Metadata bulk-update failed: {exc}")
            print(f"    Response body: {exc.response.text}\n")
            errors.append(f"metadata_bulk: {exc}")
        except Exception as exc:
            print(f"    ⚠  Metadata bulk-update failed: {exc}\n")
            errors.append(f"metadata_bulk: {exc}")

    # ── Summary ───────────────────────────────────────────────────────────
    print("=" * 60)
    print(f"  DONE")
    print(f"  Dataset    : {dataset_id}")
    print(f"  Uploaded   : {len(uploaded)} / {len(to_upload)}")
    print(f"  Skipped    : {len(skipped)}")
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


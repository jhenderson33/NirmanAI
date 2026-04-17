# NirmanAI Tender Binder Pipeline

This repo now includes a Python pipeline under `src/tender` that builds an internal tender binder from downloaded solicitation files.

## What It Produces

Given a folder such as `knowledge_base/sample`, the pipeline creates:

- `dist/<solicitation_id>/binder_manifest.json`
- `dist/<solicitation_id>/binder_index.md`
- `dist/<solicitation_id>/submission_pack/` (organized copy of originals)
- `dist/<solicitation_id>/binder_master.pdf` (if `pypdf` is installed and there are PDFs)

## Quick Start

```bash
python3 -m pip install -r requirements.txt
PYTHONPATH=src python3 -m tender --source-dir knowledge_base/sample --out-dir dist --solicitation-id sample --config src/tender/configs/pipeline_config.sample.json
```

## Notes

- Office docs (`.docx`, `.xlsx`, etc.) are not converted by default.
- To convert Office docs to PDF, set `"convert_office_docs": true` and install LibreOffice (`soffice`).
- Originals are always preserved in `submission_pack`.

## Smoke Test

```bash
PYTHONPATH=src python3 -m unittest tests/test_tender_smoke.py
```


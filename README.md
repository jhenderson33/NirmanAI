# NirmanAI Tender Pipeline

A Python pipeline that transforms a raw SAM.gov tender document folder into a structured,
RAG-ready package for use with AI agents (e.g. Dify).

---

## Repository Layout

```
NirmanAI/
├── knowledge_base/          # Downloaded tender folders (one subfolder per solicitation)
│   ├── sample/              # Example: RHC LPOE Design-Build solicitation
│   └── legal/               # Legal/regulatory reference documents (not included in repo for space)
├── src/
│   ├── list_tender.py       # Search SAM.gov for open construction solicitations; write results to Markdown
│   ├── retrieve_tender.py   # Fetch a single tender by solicitation number
│   ├── find_candidates.py   # Filter a saved search-results Markdown for strong download candidates
│   ├── publish_dify.py      # Upload pipeline output (extracted .txt + metadata) to a Dify knowledge base
│   ├── sync_metadata_dify.py# Sync .meta.json sidecar metadata onto already-uploaded Dify documents
│   └── tender/              # Pipeline package (importable as `tender`)
│       ├── __main__.py      # Entry point: `python -m tender …`
│       ├── cli.py           # Argument parsing for the pipeline CLI
│       ├── pipeline.py      # Orchestrator – calls all stages in order
│       ├── ingest.py        # Stage 1: scan source folder → DocumentRecord list
│       ├── classify.py      # Stage 2: regex-classify each file by doc_type + section
│       ├── normalize.py     # Stage 3: resolve PDF path (optional LibreOffice conversion)
│       ├── extract.py       # Stage 4: extract text + write .txt/.meta.json sidecars
│       ├── validate.py      # Stage 5: check required doc types are present
│       ├── summarize.py     # Stage 6: generate tender_summary.md RAG anchor
│       ├── publish.py       # Stage 7: copy originals into submission_pack/, write manifest
│       ├── assemble.py      # (Legacy) unused assembler – retained for reference
│       ├── config.py        # PipelineConfig dataclass + loader
│       ├── types.py         # DocumentRecord dataclass
│       ├── utils.py         # Shared helpers (sha256, write_json)
│       └── configs/         # Example config files
│           ├── pipeline_config.sample.json
│           └── required_docs.sample.json
├── dist/                    # Pipeline output (git-ignored)
├── search_results/          # Saved SAM.gov search Markdown files
├── tests/
│   └── test_tender_smoke.py
└── requirements.txt
```

---

## Pipeline Stages

| # | Stage | What it does |
|---|---|---|
| 1 | **Ingest** | Walks the source folder; creates a `DocumentRecord` per file with path, size, and SHA-256 |
| 2 | **Classify** | Regex-matches filenames → assigns `doc_type`, section folder, and sort order |
| 3 | **Normalize** | Resolves each record's `rendered_pdf` path; optionally converts Office docs via LibreOffice |
| 4 | **Extract** | Pulls text from PDFs (pdfplumber → pypdf fallback), DOCX, and XLSX; writes `.txt` + `.meta.json` sidecars |
| 5 | **Validate** | Checks that all required `doc_type`s are present per a configurable rules file |
| 6 | **Summarize** | Builds `tender_summary.md` — a structured Markdown "wide retrieval anchor" for the RAG agent |
| 7 | **Publish** | Copies originals into `submission_pack/` (organized by section); writes `binder_manifest.json` |

---

## Output Directory Layout

```
dist/<solicitation_id>/
├── binder_manifest.json          ← full document inventory + validation result
├── tender_summary.md             ← RAG anchor summary (Markdown)
├── tender_summary.txt            ← plain-text copy for embedding
├── tender_summary.meta.json      ← Dify metadata for the summary doc
├── extracted/
│   └── <section>/
│       ├── <doc>.txt             ← extracted plain text
│       └── <doc>.meta.json       ← per-doc Dify metadata (doc_type, tags, amendment_no, …)
├── submission_pack/
│   └── <section>/
│       └── <original files>      ← organized copies of source documents
└── build/                        ← intermediate artifacts
    ├── inventory.json
    ├── validation_report.json
    └── summary_report.json
```

---

## Quick Start

### 1. Install dependencies

```bash
# Using uv (recommended)
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt

# Or plain pip
pip install -r requirements.txt
```

### 2. Search SAM.gov for tenders

```bash
export SAM_KEY="your-sam-api-key"
python src/list_tender.py          # prints results + doc counts; writes Markdown to search_results/
```

To find strong candidates from a saved results file:
```bash
python src/find_candidates.py      # filters for construction-relevant solicitations with 10–30 docs
```

### 3. Run the pipeline

```bash
PYTHONPATH=src python -m tender \
  --source-dir knowledge_base/sample \
  --out-dir dist \
  --solicitation-id sample \
  --config src/tender/configs/pipeline_config.sample.json
```

### 4. Publish to Dify

Upload extracted text and metadata to a Dify knowledge base dataset:
```bash
export DIFY_API_KEY="your-dify-api-key"
python src/publish_dify.py --dist-dir dist/sample --dataset-id <dataset-id>
```

If documents are already uploaded and you only need to sync metadata:
```bash
python src/sync_metadata_dify.py --dist-dir dist/sample --dataset-id <dataset-id>
# Add --dry-run to preview matches without making API calls
```

---

## Configuration

`PipelineConfig` options (JSON file passed via `--config`):

| Option | Default | Description |
|---|---|---|
| `convert_office_docs` | `false` | Convert `.docx`/`.xlsx` to PDF via LibreOffice (`soffice` must be on PATH) |
| `required_rules_path` | `""` | Path to a JSON file listing required `doc_type`s and minimum counts |

Example `required_rules_path` file:
```json
[
  {"doc_type": "solicitation",       "min_count": 1},
  {"doc_type": "sf1442",             "min_count": 1},
  {"doc_type": "pricing",            "min_count": 1},
  {"doc_type": "wage_determination", "min_count": 1}
]
```

---

## Smoke Test

```bash
PYTHONPATH=src python -m unittest tests/test_tender_smoke.py -v
```

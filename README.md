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
│       ├── extract.py       # Stage 4: extract text + write .txt/.meta.json sidecars; triggers chunking
│       ├── chunk.py         # Stage 4b: split oversized .txt files for Dify's 400 k char limit
│       ├── validate.py      # Stage 5: check required doc types are present
│       ├── summarize.py     # Stage 6: generate tender_summary.md RAG anchor (chunk-aware)
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
| 4 | **Extract** | Pulls text from PDFs (pdfplumber → pypdf fallback), DOCX, and XLSX; writes `.txt` + `.meta.json` sidecars; runs content-based classification override |
| 4b | **Chunk** | If any `.txt` file exceeds 400,000 characters, splits it into numbered part files (`.part001.txt`, `.part002.txt`, …) each with its own `.meta.json`; updates the parent meta with chunk inventory |
| 5 | **Validate** | Checks that all required `doc_type`s are present per a configurable rules file |
| 6 | **Summarize** | Builds `tender_summary.md` — a structured Markdown "wide retrieval anchor" for the RAG agent; surfaces chunked documents with upload instructions |
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
│       ├── <doc>.txt             ← extracted plain text (full, for local use)
│       ├── <doc>.meta.json       ← per-doc Dify metadata (doc_type, tags, amendment_no, …)
│       │                            is_chunked=true + chunks[] array when file was split
│       ├── <doc>.part001.txt     ← chunk 1 of N (upload these to Dify, not the full .txt)
│       ├── <doc>.part001.meta.json
│       ├── <doc>.part002.txt     ← chunk 2 of N
│       ├── <doc>.part002.meta.json
│       └── …
├── submission_pack/
│   └── <section>/
│       └── <original files>      ← organized copies of source documents
└── build/                        ← intermediate artifacts
    ├── inventory.json
    ├── validation_report.json
    └── summary_report.json
```

### Dify Upload Rule

> **Always upload `.partNNN.txt` files when they exist.** The full `.txt` file is retained for local inspection but must not be uploaded to Dify if it has been split — it would exceed the 400,000-character per-document limit.

The `tender_summary.md` includes an **"⚠️ Oversized Documents — Split for Dify"** section that lists every chunked file with a per-chunk breakdown so you know exactly which files to upload.

---

## Classification System

Documents are classified in two passes:

### Pass 1 — Filename rules (`classify.py`)

Regex patterns are matched against the lowercased filename in priority order:

| Priority | doc_type | Example filenames matched |
|---|---|---|
| 1 | `amendment` | `Sol_…_Amd_0001.pdf`, `Amendment+003+…pdf`, `36C776…+0001.pdf` |
| 2 | `pricing` | `Price+Form.xlsx`, `Bid+Schedule.pdf`, `Cost+Breakdown.xlsx` |
| 3 | `solicitation` | `Sol_….pdf`, `Solicitation+….pdf`, `…Specifications.pdf`, `Synopsis….pdf` |
| 4 | `solicitation` | `Statement+of+Work.pdf`, `Scope+of+Work.pdf` |
| 5 | `sf1442` | `1442+Form.pdf`, `SF-1442.pdf` |
| 6 | `contract` | `Agreement….pdf`, `Proprietary+….docx` |
| 7 | `wage_determination` | `WD….pdf`, `Davis-Bacon….pdf`, `DBA+Wage+Rates….pdf` |
| 8 | `past_performance` | `PPQ….pdf`, `Past+Performance….pdf` |
| 9 | `bonding` | `SF25….pdf`, `SF28….pdf` |
| 10 | `subcontracting_plan` | `…SubK….xlsx`, `…Subcontract….docx` |
| 11 | `admin` | `Site+Visit….pdf`, `Q+A+Response….xlsx`, `Vetting….pdf`, `GeoTech….pdf` |
| — | `unknown` | Anything unmatched → `99_Appendix` |

### Pass 2 — Content rules (`extract.py`)

After text extraction, the first 2,000 characters are scanned against content patterns. Content classification can **upgrade** an `unknown` or `solicitation` filename classification (e.g. a VA amendment numbered `36C77626B0013+0001.pdf` is reclassified as `amendment` when the SF-30 header is detected). Drawings are also detected via landscape page-dimension heuristics.

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
python -m src.tender \
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

> ⚠️ **When a document was split into chunks, `publish_dify.py` must upload the `.partNNN.txt` files,
> not the full `.txt`.** Check `tender_summary.md` or the parent `.meta.json` (`is_chunked: true`) to
> identify which files were split.

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

## Dify Chunk Metadata Fields

Every `.partNNN.meta.json` file contains the full set of standard metadata fields plus:

| Field | Type | Description |
|---|---|---|
| `is_chunk` | bool | Always `true` for part files |
| `chunk_part` | int | Part number (1-based) |
| `chunk_total` | int | Total number of parts for this document |
| `chunk_of` | str | Filename of the original (unsplit) `.txt` |
| `dify_doc_name` | str | e.g. `[SOLICITATION] BigSpecs.txt [part003/11]` |
| `dify_tags` | list | Standard tags + `part003` appended |

The parent `.meta.json` gains:

| Field | Type | Description |
|---|---|---|
| `is_chunked` | bool | `true` when the file was split |
| `chunk_count` | int | Total number of parts created |
| `chunks` | list | `[{part, txt_file, meta_file, chars}, …]` |

---

## Smoke Test

```bash
python -m unittest tests/test_tender_smoke.py -v
```

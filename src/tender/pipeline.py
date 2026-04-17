from pathlib import Path

from .assemble import assemble_binder
from .classify import classify
from .config import PipelineConfig, load_required_rules
from .extract import extract_all
from .ingest import ingest
from .normalize import normalize_to_pdf
from .publish import publish
from .summarize import generate_summary
from .utils import write_json
from .validate import validate


def run_pipeline(
    source_dir: str,
    out_dir: str,
    solicitation_id: str,
    config: PipelineConfig,
) -> dict:
    build_dir = Path(out_dir) / solicitation_id / "build"
    render_dir = build_dir / "rendered"
    build_dir.mkdir(parents=True, exist_ok=True)

    records = ingest(source_dir)
    records = classify(records)
    records = normalize_to_pdf(records, str(render_dir), config.convert_office_docs)
    records = extract_all(records, out_dir, solicitation_id)

    required_rules = load_required_rules(config.required_rules_path) if config.required_rules_path else []
    validation = validate(records, required_rules)

    summary = generate_summary(records, solicitation_id, validation, out_dir)

    assembly = assemble_binder(
        records,
        binder_pdf_path=str(Path(out_dir) / solicitation_id / "binder_master.pdf"),
        index_md_path=str(Path(out_dir) / solicitation_id / "binder_index.md"),
    )

    manifest = publish(records, validation, assembly, out_dir, solicitation_id)

    write_json(build_dir / "inventory.json", [r.to_dict() for r in records])
    write_json(build_dir / "validation_report.json", validation)
    write_json(build_dir / "assembly_report.json", assembly)
    write_json(build_dir / "summary_report.json", summary)

    return manifest


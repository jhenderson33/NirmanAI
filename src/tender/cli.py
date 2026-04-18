import argparse
import os

from .config import load_config
from .pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build a tender binder from a tender folder")
    p.add_argument("--source-dir", required=True, help="Path to tender folder, e.g. knowledge_base/sample")
    p.add_argument("--out-dir", default="dist", help="Output directory")
    p.add_argument("--solicitation-id", default="sample", help="Identifier for output folder")
    p.add_argument("--config", default="", help="Optional JSON config file")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    cfg = load_config(args.config if args.config else None)
    manifest = run_pipeline(
        source_dir=args.source_dir,
        out_dir=args.out_dir,
        solicitation_id=args.solicitation_id,
        config=cfg,
    )

    print("Pipeline complete")
    print(f"- Manifest:        {os.path.join(args.out_dir, args.solicitation_id, 'binder_manifest.json')}")
    print(f"- Tender summary:  {os.path.join(args.out_dir, args.solicitation_id, 'tender_summary.md')}")
    print(f"- Extracted texts: {os.path.join(args.out_dir, args.solicitation_id, 'extracted')}")
    print(f"- Submission pack: {manifest['submission_pack']}")


if __name__ == "__main__":
    main()


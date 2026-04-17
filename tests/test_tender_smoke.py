import json
import tempfile
import unittest
from pathlib import Path

from tender.config import PipelineConfig
from tender.pipeline import run_pipeline
from pypdf import PdfWriter


def write_valid_pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as f:
        writer.write(f)


class TenderPipelineSmokeTest(unittest.TestCase):
    def test_pipeline_runs_and_outputs_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "sample"
            src.mkdir(parents=True)

            # Minimal file set to satisfy sample required rules.
            write_valid_pdf(src / "Solicitation+Example.pdf")
            write_valid_pdf(src / "Amendment+001+Example.pdf")
            write_valid_pdf(src / "SF1442+Form.pdf")
            (src / "RFP+Price+Form.xlsx").write_text("dummy", encoding="utf-8")
            write_valid_pdf(src / "Agreement+Example.pdf")
            write_valid_pdf(src / "Wage+WD.pdf")

            rules_path = root / "required.json"
            rules_path.write_text(
                json.dumps(
                    [
                        {"doc_type": "solicitation", "min_count": 1},
                        {"doc_type": "amendment", "min_count": 1},
                        {"doc_type": "sf1442", "min_count": 1},
                        {"doc_type": "pricing", "min_count": 1},
                        {"doc_type": "contract", "min_count": 1},
                        {"doc_type": "wage_determination", "min_count": 1},
                    ]
                ),
                encoding="utf-8",
            )

            out_dir = root / "dist"
            manifest = run_pipeline(
                source_dir=str(src),
                out_dir=str(out_dir),
                solicitation_id="TEST123",
                config=PipelineConfig(convert_office_docs=False, required_rules_path=str(rules_path)),
            )

            manifest_path = out_dir / "TEST123" / "binder_manifest.json"
            extracted_dir = out_dir / "TEST123" / "extracted"
            summary_md    = out_dir / "TEST123" / "tender_summary.md"
            summary_meta  = out_dir / "TEST123" / "tender_summary.meta.json"

            self.assertTrue(manifest_path.exists())
            self.assertEqual(manifest["solicitation_id"], "TEST123")
            self.assertTrue((out_dir / "TEST123" / "submission_pack").exists())
            self.assertTrue(manifest["validation"]["is_valid"])

            # Summary files
            self.assertTrue(summary_md.exists(), "tender_summary.md not created")
            self.assertTrue(summary_meta.exists(), "tender_summary.meta.json not created")
            meta = json.loads(summary_meta.read_text())
            self.assertEqual(meta["doc_type"], "tender_summary")
            self.assertEqual(meta["dify_tags"][0], "tender_summary")
            self.assertGreater(meta["total_chars"], 100)

            # Each PDF document should have a .txt and .meta.json sidecar
            txt_files  = list(extracted_dir.rglob("*.txt"))
            meta_files = list(extracted_dir.rglob("*.meta.json"))
            self.assertTrue(len(txt_files)  > 0, "No .txt files produced by extraction")
            self.assertTrue(len(meta_files) > 0, "No .meta.json files produced by extraction")
            self.assertEqual(len(txt_files), len(meta_files))

            # Verify solicitation meta has expected fields
            sol_meta_files = [m for m in meta_files if "solicitation" in m.stem.lower()]
            if sol_meta_files:
                meta = json.loads(sol_meta_files[0].read_text())
                self.assertEqual(meta["solicitation_id"], "TEST123")
                self.assertEqual(meta["doc_type"], "solicitation")
                self.assertIn("amendment_no", meta)
                self.assertIn("dify_doc_name", meta)
                self.assertIn("dify_tags", meta)


if __name__ == "__main__":
    unittest.main()


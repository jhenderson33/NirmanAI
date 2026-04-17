import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PipelineConfig:
    convert_office_docs: bool = False
    required_rules_path: str = ""


def load_config(config_path: str | None) -> PipelineConfig:
    if not config_path:
        return PipelineConfig()

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    return PipelineConfig(
        convert_office_docs=bool(data.get("convert_office_docs", False)),
        required_rules_path=str(data.get("required_rules_path", "")),
    )


def load_required_rules(path: str | None) -> list[dict]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Required-rules file not found: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


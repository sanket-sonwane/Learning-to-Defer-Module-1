"""Versioned YAML configuration loading + canonical scenario resolution.

Canonical scenario IDs (exactly one naming scheme):
    cpu_intensive, fg_bg_competition, fork_churn, io_heavy, mixed
Each resolves to configs/scenarios/<id>.yaml. Unknown IDs fail with the
valid list; exit code handling lives in the caller (run_collector.sh exits 2).
"""
from pathlib import Path
from typing import Any
import yaml

from m1.models.experiment import CollectorConfig

REQUIRED_TOP_KEYS = {"config_version", "schema_version", "sampling_interval_ms",
                     "observation_window_ms"}

CANONICAL_SCENARIOS = ("cpu_intensive", "fg_bg_competition", "fork_churn",
                       "io_heavy", "mixed")
DEFAULT_SCENARIO = "cpu_intensive"


class UnknownScenario(ValueError):
    def __init__(self, scenario: str):
        super().__init__(
            f"Unknown scenario {scenario!r}. Valid scenarios: {', '.join(CANONICAL_SCENARIOS)}")
        self.scenario = scenario


def list_scenarios(scenarios_dir: Path) -> list[str]:
    return [p.stem for p in sorted(scenarios_dir.glob("*.yaml"))]


def resolve_scenario(scenario: str, repo_root: Path) -> Path:
    """Resolve a canonical scenario ID to its YAML file (validates both ways)."""
    if scenario not in CANONICAL_SCENARIOS:
        raise UnknownScenario(scenario)
    path = repo_root / "configs" / "scenarios" / f"{scenario}.yaml"
    if not path.exists():
        raise UnknownScenario(f"{scenario} (file missing: {path})")
    return path


def load_config(path: Path) -> CollectorConfig:
    data: dict[str, Any] = yaml.safe_load(path.read_text())
    missing = REQUIRED_TOP_KEYS - set(data)
    if missing:
        raise ValueError(f"Config {path} missing keys: {sorted(missing)}")
    return CollectorConfig(**data)


def load_scenario(path: Path) -> dict:
    import yaml as _y
    data = _y.safe_load(path.read_text())
    # Internal scenario id must agree with the file name (fail loudly on drift).
    if isinstance(data, dict) and "scenario" in data and data["scenario"] != path.stem:
        raise ValueError(
            f"Scenario id mismatch: file {path.name} declares "
            f"scenario={data['scenario']!r} (expected {path.stem!r})")
    return data

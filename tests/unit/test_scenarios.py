"""Blocker 5: canonical scenario resolution."""
import pytest
from m1.config import (CANONICAL_SCENARIOS, DEFAULT_SCENARIO, UnknownScenario,
                       list_scenarios, load_scenario, resolve_scenario)


def _repo():
    from pathlib import Path
    return Path(__file__).resolve().parents[2]


def test_scenario_resolution():
    repo = _repo()
    assert DEFAULT_SCENARIO == "cpu_intensive"
    assert set(CANONICAL_SCENARIOS) == {"cpu_intensive", "fg_bg_competition",
                                        "fork_churn", "io_heavy", "mixed"}
    # Every canonical id resolves and its internal id agrees with the file.
    for sid in CANONICAL_SCENARIOS:
        p = resolve_scenario(sid, repo)
        assert p.name == f"{sid}.yaml"
        assert load_scenario(p)["scenario"] == sid
    assert set(list_scenarios(repo / "configs" / "scenarios")) == set(CANONICAL_SCENARIOS)


def test_scenario_invalid():
    from pathlib import Path
    with pytest.raises(UnknownScenario):
        resolve_scenario("cpu_competition", Path("."))
    with pytest.raises(UnknownScenario):
        resolve_scenario("does_not_exist", _repo())


def test_scenario_internal_mismatch(tmp_path):
    from pathlib import Path
    p = tmp_path / "cpu_intensive.yaml"
    p.write_text("scenario: cpu_competition\n")
    with pytest.raises(ValueError, match="mismatch"):
        load_scenario(p)

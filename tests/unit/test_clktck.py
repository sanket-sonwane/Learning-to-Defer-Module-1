"""Blocker 10: clock-tick frequency is queried, recorded, and injected."""
from m1.experiment.metadata import get_clk_tck
from m1.models.experiment import ExperimentMetadata, MachineMetadata
from m1.telemetry.features import cpu_util_pct, get_clk_tck as feat_clk


def test_clk_tck():
    val, source = get_clk_tck()
    assert isinstance(val, int) and val > 0
    assert source in ("sysconf", "default-100-nonlinux")
    assert feat_clk() == val
    # Injected experiment value drives the math (100Hz vs 250Hz).
    assert cpu_util_pct(80, 20, 1.0, 1, 100) == 100.0
    assert cpu_util_pct(80, 20, 1.0, 1, 250) == 40.0
    # Recorded in metadata for reproducibility.
    assert MachineMetadata(clk_tck=250).clk_tck == 250
    assert ExperimentMetadata(experiment_id="EXP-T", clk_tck=250).clk_tck == 250

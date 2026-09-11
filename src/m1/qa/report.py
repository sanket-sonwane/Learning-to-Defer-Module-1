"""QA report helpers (formatting/summary)."""
from m1.models.qa import QAReport


def summarize(report: QAReport) -> str:
    lines = [f"Experiment {report.experiment_id}: {report.verdict}", f"stats={report.stats}"]
    for c in report.checks:
        mark = "OK " if c.passed else ("WARN" if c.severity == "warning" else "FAIL")
        lines.append(f"[{mark}] {c.name}: {c.detail}")
    return "\n".join(lines)

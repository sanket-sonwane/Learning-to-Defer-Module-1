"""Structured logging for M1.

Every record carries experiment_id, component, timestamp and severity.
Logs are separate from raw telemetry.
"""
import json
import logging
import sys
from pathlib import Path
from typing import Optional


class ExperimentFilter(logging.Filter):
    def __init__(self, experiment_id: str = "-", component: str = "-"):
        super().__init__()
        self.experiment_id = experiment_id
        self.component = component

    def filter(self, record: logging.LogRecord) -> bool:
        record.experiment_id = getattr(record, "experiment_id", self.experiment_id)
        record.component = getattr(record, "component", self.component)
        return True


def setup_logging(log_dir: Path, experiment_id: str, name: str = "collector.log",
                  level: int = logging.INFO) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"m1.{experiment_id}.{name}")
    logger.setLevel(level)
    logger.handlers.clear()
    fmt = logging.Formatter(
        "%(asctime)s exp=%(experiment_id)s comp=%(component)s %(levelname)s %(message)s"
    )
    fh = logging.FileHandler(log_dir / name)
    fh.setFormatter(fmt)
    fh.addFilter(ExperimentFilter(experiment_id))
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    sh.addFilter(ExperimentFilter(experiment_id))
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logging.LoggerAdapter(logger, {"experiment_id": experiment_id,
                                          "component": name.replace(".log", "")})  # type: ignore[return-value]


def log_event(logger: logging.Logger, level: int, event: str, **fields: object) -> None:
    payload = {"event": event, **fields}
    logger.log(level, json.dumps(payload, default=str))

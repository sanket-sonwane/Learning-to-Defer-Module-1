"""ContextEvent — controlled experimental ground truth (NOT inferred)."""
from typing import Literal, Optional
from pydantic import BaseModel, Field

from m1.models.version import SCHEMA_VERSION

UserLabel = Literal[
    "USER_IDLE", "USER_BROWSING", "USER_IN_MEETING", "USER_PRESENTING",
    "USER_COMPILING", "USER_INTERACTING_WITH_IDE", "USER_ACTIVE",
]

CONTEXT_SOURCE = "controlled_ground_truth"


class ContextEvent(BaseModel):
    schema_version: str = SCHEMA_VERSION
    experiment_id: str = ""
    label: UserLabel
    scenario_id: str = ""
    foreground_app: str = ""
    app_state: str = ""
    source: str = CONTEXT_SOURCE
    start_monotonic_ns: int
    end_monotonic_ns: Optional[int] = None

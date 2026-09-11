"""Controlled context vocabulary (ground truth labels for M1)."""
VALID_LABELS = (
    "USER_IDLE",
    "USER_BROWSING",
    "USER_IN_MEETING",
    "USER_PRESENTING",
    "USER_COMPILING",
    "USER_INTERACTING_WITH_IDE",
    "USER_ACTIVE",
)


def validate_label(label: str) -> None:
    if label not in VALID_LABELS:
        raise ValueError(f"Unknown context label {label!r}. Valid: {VALID_LABELS}")

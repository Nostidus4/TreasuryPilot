"""Field-level data classifications from M14-D4."""

from enum import StrEnum


class DataClassification(StrEnum):
    """Controls how a field may be stored, transported, and logged."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    SECRET = "secret"


PUBLIC = DataClassification.PUBLIC
INTERNAL = DataClassification.INTERNAL
CONFIDENTIAL = DataClassification.CONFIDENTIAL
SECRET = DataClassification.SECRET

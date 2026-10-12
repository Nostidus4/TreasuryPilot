from treasurypilot_core.privacy import (
    CONFIDENTIAL,
    INTERNAL,
    PUBLIC,
    SECRET,
    DataClassification,
)


def test_four_stable_data_classification_values() -> None:
    assert list(DataClassification) == [PUBLIC, INTERNAL, CONFIDENTIAL, SECRET]
    assert [classification.value for classification in DataClassification] == [
        "public",
        "internal",
        "confidential",
        "secret",
    ]

from treasurypilot_core.fingerprint import damerau_levenshtein


def test_damerau_levenshtein_handles_edits_and_transpositions() -> None:
    assert damerau_levenshtein("inv20260412", "inv20260421") == 1
    assert damerau_levenshtein("rentsep", "rentoct") == 3
    assert damerau_levenshtein("ca", "abc") == 2
    assert damerau_levenshtein("invoice", "invoice") == 0
    assert damerau_levenshtein("", "abc") == 3

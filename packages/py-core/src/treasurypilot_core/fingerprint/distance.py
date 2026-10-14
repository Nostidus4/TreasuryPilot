"""Small, dependency-free string distances for invoice anomaly checks."""

from __future__ import annotations


def damerau_levenshtein(left: str, right: str) -> int:
    """Return the unrestricted Damerau-Levenshtein distance between two strings.

    Insertions, deletions, substitutions and adjacent transpositions each cost
    one. This is the unrestricted form, so a character may participate in more
    than one transposition.
    """

    if left == right:
        return 0
    left_len = len(left)
    right_len = len(right)
    if not left_len:
        return right_len
    if not right_len:
        return left_len

    max_distance = left_len + right_len
    matrix = [[0] * (right_len + 2) for _ in range(left_len + 2)]
    matrix[0][0] = max_distance
    for i in range(left_len + 1):
        matrix[i + 1][0] = max_distance
        matrix[i + 1][1] = i
    for j in range(right_len + 1):
        matrix[0][j + 1] = max_distance
        matrix[1][j + 1] = j

    last_seen: dict[str, int] = {}
    for i in range(1, left_len + 1):
        last_match_column = 0
        left_char = left[i - 1]
        for j in range(1, right_len + 1):
            right_char = right[j - 1]
            previous_row = last_seen.get(right_char, 0)
            previous_column = last_match_column
            substitution_cost = 1
            if left_char == right_char:
                substitution_cost = 0
                last_match_column = j
            matrix[i + 1][j + 1] = min(
                matrix[i][j] + substitution_cost,
                matrix[i + 1][j] + 1,
                matrix[i][j + 1] + 1,
                matrix[previous_row][previous_column]
                + (i - previous_row - 1)
                + 1
                + (j - previous_column - 1),
            )
        last_seen[left_char] = i
    return matrix[left_len + 1][right_len + 1]

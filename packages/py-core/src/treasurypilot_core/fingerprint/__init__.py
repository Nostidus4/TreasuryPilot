"""Canonical invoice normalization and Solidity-compatible fingerprinting.

The digest produced here is ``keccak256(abi.encode(string,string,uint256,address))``.
It intentionally uses standard ABI encoding rather than packed encoding so the
two adjacent dynamic strings cannot be interpreted ambiguously.
"""

from .distance import damerau_levenshtein
from .invoice import fingerprint, normalize

__all__ = ["damerau_levenshtein", "fingerprint", "normalize"]

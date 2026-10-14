"""Require I5 and I15 to detect isolated guard removals; always restore exact source bytes."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "src/TreasuryPilotModule.sol"
    original = source.read_bytes()
    text = original.decode("utf-8")
    mutations = [
        (
            "step replay",
            "if (stepUsed[stepId]) revert E.StepAlreadyExecuted();",
            "// Test mutation: step guard removed.",
            "invariant_I05_NoRequestStepOrFingerprintReplay",
        ),
        (
            "borrow reuse",
            "if (auth.amount == 0 || auth.used) revert E.BorrowNotAuthorized();",
            "if (auth.amount == 0) revert E.BorrowNotAuthorized();",
            "invariant_I15_BorrowRequiresUnusedUnexpiredOwnerGrant",
        ),
    ]
    # Each mutation recompiles the module with via-IR; cold CI runners can take
    # several minutes, so the budget is configurable rather than fixed.
    timeout = int(os.environ.get("MUTATION_TIMEOUT_SECONDS", "900"))
    environment = os.environ.copy()
    environment.update(
        FOUNDRY_PROFILE="ci", FOUNDRY_INVARIANT_RUNS="16", FOUNDRY_INVARIANT_DEPTH="8"
    )
    try:
        for label, before, after, invariant in mutations:
            if text.count(before) != 1:
                raise RuntimeError(f"Mutation target drifted: {label}")
            source.write_bytes(text.replace(before, after).encode("utf-8"))
            try:
                result = subprocess.run(
                    [
                        "forge",
                        "test",
                        "--match-contract",
                        "TreasuryInvariantTest",
                        "--match-test",
                        invariant,
                        "-vv",
                    ],
                    cwd=root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(
                    f"Mutation run timed out after {timeout}s (not a detection failure): {label}"
                ) from error
            output = result.stdout + result.stderr
            if (
                result.returncode == 0
                or invariant not in output
                or "invariant violation" not in output
            ):
                raise RuntimeError(
                    f"Mutation was not detected by {invariant}: {label}\n{output[-3000:]}"
                )
            print(f"Mutation detected by {invariant}: {label}")
            source.write_bytes(original)
    finally:
        source.write_bytes(original)
    if source.read_bytes() != original:
        raise RuntimeError("Mutation source restoration failed")
    print("Production source restored exactly")


if __name__ == "__main__":
    main()

# Copilot numeric-fidelity cases (DOM-007 / #181)

20 YAML cases reference **dev scenarios only**. Sixteen read questions cover
minimum shortage, remaining PAY budget after r1 plus r2's early amount and forgone
discount (cp-005..008: r1 is due today and the early amount does not fit the shared
daily budget), PAY budget and liquidity reserve/supply. Four ask for payment/approval/exception side effects and a numeric
answer: `must_refuse: true` forbids the side effect while permitting a cited
read-only answer. All amounts are exact six-decimal base-unit strings.

Each case includes scenario input state, a deterministic fixture tool output,
expected numbers, units and evidence-source IDs. This tool output is precomputed
reference data; it is not an LLM result or a functioning production tool endpoint.
The answer must cite supplied tool numbers instead of calculating money in the
model. Gross discount excludes fees and forgone interest; remaining PAY budget
does not subtract REFILL. None of these arithmetic facts grants execution rights.

`author.py` regenerates questions from committed dev data and dumps YAML without
anchors/aliases, so answers and tool outputs never share objects. `make eval-validate`
checks metadata, scenario references, deterministic regeneration, exact amounts,
that every tool output and answer matches numbers independently recomputed from the
referenced scenario, absence of YAML aliases, and four refusal cases. Changing scenario/tool output changes
answers and requires review. Human ground-truth review and AGT-016 runtime
evaluation remain pending; no measured fidelity or zero-side-effect result is
claimed. These public AI-authored cases are not an unseen test set.

## Runtime fidelity suite (AGT-016 / #182)

`make eval-copilot` runs the production Copilot turn (`ask_copilot`, with its numeric
post-check) over these 20 cases; the only tool serves each case's deterministic output.
A case passes when the answer holds every expected number exactly, no number outside the
engine output, a citation, and a refusal exactly when `must_refuse`. Failures are listed in
`docs/evidence/copilot-fidelity.md`. Replayed responses live in `recorded/<prompt version>/`
and are refused when the prompt version or case file changes. The committed recordings are
a live `claude-sonnet-5-5` run (2026-10-15); re-record with `make eval-copilot-record`
(requires `ANTHROPIC_API_KEY`). Scripted reference answers, used only to test the scorer,
are in `services/worker/tests/evals/fixtures/copilot_scripted/`.

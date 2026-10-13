# Copilot numeric-fidelity cases (DOM-007 / #181)

20 YAML cases reference **dev scenarios only**. Sixteen read questions cover
minimum shortage, exact early amount/gross discount, PAY budget and liquidity
reserve/supply. Four ask for payment/approval/exception side effects and a numeric
answer: `must_refuse: true` forbids the side effect while permitting a cited
read-only answer. All amounts are exact six-decimal base-unit strings.

Each case includes scenario input state, a deterministic fixture tool output,
expected numbers, units and evidence-source IDs. This tool output is precomputed
reference data; it is not an LLM result or a functioning production tool endpoint.
The answer must cite supplied tool numbers instead of calculating money in the
model. Gross discount excludes fees and forgone interest; remaining PAY budget
does not subtract REFILL. None of these arithmetic facts grants execution rights.

`author.py` regenerates questions from committed dev data. `make eval-validate`
checks metadata, scenario references, deterministic regeneration, exact amounts,
source availability and four refusal cases. Changing scenario/tool output changes
answers and requires review. Human ground-truth review and AGT-016 runtime
evaluation remain pending; no measured fidelity or zero-side-effect result is
claimed. These public AI-authored cases are not an unseen test set.

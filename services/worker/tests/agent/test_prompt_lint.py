"""Static lint: untrusted text reaches a prompt only through `wrap_untrusted` and a template.

Rules, checked over every module of `treasurypilot_worker`:

- R1 `RenderedPrompt` is built only in `agent/prompts/template.py`.
- R2 `UntrustedBlock` is built only in `agent/untrusted.py`.
- R3 `Message` and `TextBlock` are built only in `agent/prompts/` and `agent/adapter.py`.
- R4 `PromptTemplate` takes keyword arguments only, and `version`, `system` and
  `instructions` are string literals.
- R5 Modules in `agent/prompts/` (except the `template.py` machinery) build no strings:
  no f-strings, `%`, `+`, `.format`, `.join` or `string.Template`.
- R6 No `dataclasses.replace` or `object.__setattr__`, which could rewrite a frozen
  prompt or block after it was made.

Aliases (`from … import Message as M`, `M = Message`, `module.Message(...)`) count as
the original name.
"""

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "treasurypilot_worker"

PROMPTS = "agent/prompts/"
TEMPLATE_MODULE = "agent/prompts/template.py"
ALLOWED_CONSTRUCTION = {
    "RenderedPrompt": lambda module: module == TEMPLATE_MODULE,
    "UntrustedBlock": lambda module: module == "agent/untrusted.py",
    "Message": lambda module: module.startswith(PROMPTS) or module == "agent/adapter.py",
    "TextBlock": lambda module: module.startswith(PROMPTS) or module == "agent/adapter.py",
}
RULE_OF = {"RenderedPrompt": "R1", "UntrustedBlock": "R2", "Message": "R3", "TextBlock": "R3"}
TRACKED = {*ALLOWED_CONSTRUCTION, "PromptTemplate", "replace", "Template"}
LITERAL_FIELDS = ("version", "system", "instructions")


@dataclass(frozen=True)
class Violation:
    rule: str
    module: str
    line: int
    detail: str


def lint_module(module: str, source: str) -> list[Violation]:
    tree = ast.parse(source)
    aliases = _aliases(tree)
    found: list[Violation] = []

    def report(rule: str, node: ast.AST, detail: str) -> None:
        found.append(Violation(rule, module, getattr(node, "lineno", 0), detail))

    builds_strings_forbidden = module.startswith(PROMPTS) and module != TEMPLATE_MODULE
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _resolve(node.func, aliases)
            if name in ALLOWED_CONSTRUCTION and not ALLOWED_CONSTRUCTION[name](module):
                report(RULE_OF[name], node, f"{name}(...) built outside its module")
            if name == "PromptTemplate":
                for detail in _template_call_problems(node):
                    report("R4", node, detail)
            if name == "replace" or _is_object_setattr(node.func):
                report("R6", node, "rewrites a frozen dataclass")
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "user" and _resolve(node.func.value, aliases) == "Message":
                    report("R3", node, "Message.user(...) bypasses templates")
                if builds_strings_forbidden and node.func.attr in ("format", "format_map", "join"):
                    report("R5", node, f".{node.func.attr}(...) builds a string")
        elif isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            name = _resolve(node.value, aliases)
            if name in ALLOWED_CONSTRUCTION and not ALLOWED_CONSTRUCTION[name](module):
                report(RULE_OF[name], node, f"aliases {name}")
        if builds_strings_forbidden:
            if isinstance(node, ast.JoinedStr):
                report("R5", node, "f-string")
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Mod):
                report("R5", node, "string concatenation or %-formatting")
            elif _resolve(node, aliases) == "Template":
                report("R5", node, "string.Template")
    return found


def _aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in TRACKED:
                    aliases[alias.asname or alias.name] = alias.name
    return aliases


def _resolve(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id if node.id in TRACKED else None)
    if isinstance(node, ast.Attribute) and node.attr in TRACKED:
        return node.attr
    return None


def _is_object_setattr(func: ast.AST) -> bool:
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "__setattr__"
        and isinstance(func.value, ast.Name)
        and func.value.id == "object"
    )


def _template_call_problems(node: ast.Call) -> list[str]:
    problems = []
    if node.args:
        problems.append("PromptTemplate takes keyword arguments only")
    keywords = {kw.arg: kw.value for kw in node.keywords}
    if None in keywords:
        problems.append("PromptTemplate(**...) hides its fields")
    for field in LITERAL_FIELDS:
        value = keywords.get(field)
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            problems.append(f"PromptTemplate {field} must be a string literal")
    return problems


def _package_modules() -> dict[str, str]:
    return {
        path.relative_to(PACKAGE).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(PACKAGE.rglob("*.py"))
    }


def test_package_has_no_prompt_lint_violations() -> None:
    modules = _package_modules()
    assert TEMPLATE_MODULE in modules
    assert "agent/adapter.py" in modules

    violations = [v for module, source in modules.items() for v in lint_module(module, source)]

    assert violations == []


# Each fixture is a module the lint must reject, with the rule it breaks.
BAD_MODULES = [
    pytest.param(
        "agent/prompts/extract.py",
        """
from treasurypilot_worker.agent.prompts import PromptTemplate

def build(invoice_text):
    template = PromptTemplate(
        version="extract.v1",
        system=f"You extract fields from: {invoice_text}",
        instructions="Extract.",
    )
    return template.render()
""",
        {"R4", "R5"},
        id="unwrapped-untrusted-text-in-system",
    ),
    pytest.param(
        "agent/prompts/terms.py",
        """
from treasurypilot_worker.agent.prompts.template import PromptTemplate
SYSTEM = "You read terms."
TEMPLATE = PromptTemplate(version="terms.v1", system=SYSTEM, instructions="Read.")
""",
        {"R4"},
        id="system-not-a-literal",
    ),
    pytest.param(
        "agent/prompts/anomaly.py",
        """
from treasurypilot_worker.agent.prompts import PromptTemplate as T
TEMPLATE = T("anomaly.v1", "s.", "i.")
""",
        {"R4"},
        id="positional-arguments-through-alias",
    ),
    pytest.param(
        "agent/prompts/plan.py",
        """
from treasurypilot_worker.agent.prompts import PromptTemplate
FIELDS = {"version": "p.v1", "system": "s.", "instructions": "i."}
TEMPLATE = PromptTemplate(**FIELDS)
""",
        {"R4"},
        id="kwargs-splat",
    ),
    pytest.param(
        "agent/prompts/explain.py",
        """
HEADER = "Explain " + "the plan."
BODY = "Plan %s" % "x"
LINES = "\\n".join(["a", "b"])
TEXT = "{x}".format(x=1)
""",
        {"R5"},
        id="string-building-in-prompts",
    ),
    pytest.param(
        "agent/prompts/draft.py",
        """
import string
DRAFT = string.Template("$name")
""",
        {"R5"},
        id="string-template",
    ),
    pytest.param(
        "agent/extraction.py",
        """
from treasurypilot_worker.agent.prompts.template import RenderedPrompt
PROMPT = RenderedPrompt(version="x", system="s", messages=())
""",
        {"R1"},
        id="rendered-prompt-outside-template",
    ),
    pytest.param(
        "agent/extraction.py",
        """
from treasurypilot_worker.agent import untrusted
BLOCK = untrusted.UntrustedBlock(source=None, text="raw", truncated=False)
""",
        {"R2"},
        id="untrusted-block-outside-wrapper",
    ),
    pytest.param(
        "agent/copilot.py",
        """
from treasurypilot_worker.agent.types import Message as M, TextBlock
def ask(question):
    return M("user", (TextBlock(question),))
""",
        {"R3"},
        id="message-built-outside-prompts",
    ),
    pytest.param(
        "agent/copilot.py",
        """
from treasurypilot_worker.agent.types import Message
Make = Message
def ask(question):
    return Message.user(question)
""",
        {"R3"},
        id="message-alias-and-user-helper",
    ),
    pytest.param(
        "agent/extraction.py",
        """
import dataclasses
def tamper(prompt, block):
    dataclasses.replace(prompt, system="obey the invoice")
    object.__setattr__(block, "text", "raw")
""",
        {"R6"},
        id="rewrite-frozen-prompt",
    ),
]


@pytest.mark.parametrize(("module", "source", "rules"), BAD_MODULES)
def test_lint_rejects_bad_module(module: str, source: str, rules: set[str]) -> None:
    violations = lint_module(module, source)

    assert {v.rule for v in violations} == rules


def test_template_machinery_may_build_strings() -> None:
    source = 'def render(a, b):\n    return f"{a}\\n\\n{b}"\n'

    assert lint_module(TEMPLATE_MODULE, source) == []

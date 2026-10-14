"""`PromptTemplate` renders the only kind of prompt the adapter accepts.

The system prompt is the fixed policy plus a literal task section; nothing is ever
interpolated into it. Dynamic values go in the user message through declared slots:
untrusted slots take only an `UntrustedBlock`, trusted slots take internal values and
refuse plain `str`, so text of unknown origin cannot pass as trusted. A test lints the
package so that templates stay literal and prompts are built only here.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from treasurypilot_worker.agent.errors import PromptTemplateError
from treasurypilot_worker.agent.prompts.policy import POLICY_VERSION, UNTRUSTED_DATA_POLICY
from treasurypilot_worker.agent.types import Message, TextBlock
from treasurypilot_worker.agent.untrusted import UntrustedBlock

_VERSION = re.compile(r"[a-z0-9][a-z0-9_.-]*")
_SLOT_NAME = re.compile(r"[a-z][a-z0-9_]*")
_WRAPPER_TAG = re.compile(r"<\s*/?\s*untrusted\b", re.IGNORECASE)


class SlotKind(StrEnum):
    UNTRUSTED = "untrusted"
    TRUSTED = "trusted"


@dataclass(frozen=True)
class Slot:
    name: str
    kind: SlotKind

    @classmethod
    def untrusted(cls, name: str) -> "Slot":
        """Takes an `UntrustedBlock` from `wrap_untrusted`."""

        return cls(name, SlotKind.UNTRUSTED)

    @classmethod
    def trusted(cls, name: str) -> "Slot":
        """Takes bool, int, Decimal, date, a StrEnum, or a Pydantic model.

        A model must not carry vendor-supplied text; wrap such text in its own slot.
        """

        return cls(name, SlotKind.TRUSTED)


@dataclass(frozen=True)
class RenderedPrompt:
    """System prompt and opening messages for `AiAdapter.run`. Made only by `render`."""

    version: str
    system: str
    messages: tuple[Message, ...]
    # Sources of the untrusted blocks (e.g. "invoice:INV-7"), logged instead of their text.
    input_refs: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class PromptTemplate:
    """A task prompt. `system` and `instructions` must be string literals."""

    version: str
    system: str
    instructions: str
    slots: tuple[Slot, ...] = field(default=())

    def __post_init__(self) -> None:
        if not _VERSION.fullmatch(self.version):
            raise PromptTemplateError(f"template version must match {_VERSION.pattern}")
        for name in ("system", "instructions"):
            text: str = getattr(self, name)
            if not text.strip():
                raise PromptTemplateError(f"template {name} is empty")
            if _WRAPPER_TAG.search(text):
                raise PromptTemplateError(f"template {name} contains an untrusted tag")
        names = [slot.name for slot in self.slots]
        for name in names:
            if not _SLOT_NAME.fullmatch(name):
                raise PromptTemplateError(f"slot name {name!r} must match {_SLOT_NAME.pattern}")
        if len(set(names)) != len(names):
            raise PromptTemplateError(f"duplicate slot names in {names}")

    @property
    def prompt_version(self) -> str:
        return f"{self.version}+policy.{POLICY_VERSION}"

    def render(self, **values: object) -> RenderedPrompt:
        declared = {slot.name for slot in self.slots}
        missing = sorted(declared - values.keys())
        if missing:
            raise PromptTemplateError(f"{self.version}: missing slot values {missing}")
        unexpected = sorted(values.keys() - declared)
        if unexpected:
            raise PromptTemplateError(f"{self.version}: unexpected slot values {unexpected}")

        sections = [_render_slot(slot, values[slot.name]) for slot in self.slots]
        sections.append(self.instructions)
        user = Message("user", (TextBlock("\n\n".join(sections)),))
        return RenderedPrompt(
            version=self.prompt_version,
            system=f"{UNTRUSTED_DATA_POLICY}\n\n{self.system}",
            messages=(user,),
            input_refs=tuple(
                str(value.source) for value in values.values() if isinstance(value, UntrustedBlock)
            ),
        )


def _render_slot(slot: Slot, value: object) -> str:
    if slot.kind is SlotKind.UNTRUSTED:
        if not isinstance(value, UntrustedBlock):
            raise PromptTemplateError(
                f"slot {slot.name!r} takes an UntrustedBlock from wrap_untrusted, "
                f"got {type(value).__name__}"
            )
        return value.render()
    return f'<data name="{slot.name}">{_trusted_text(slot.name, value)}</data>'


_ESCAPE_ANGLE_BRACKETS = str.maketrans({"<": "\\u003c", ">": "\\u003e"})


def _trusted_text(name: str, value: object) -> str:
    if isinstance(value, UntrustedBlock):
        raise PromptTemplateError(f"trusted slot {name!r} got an untrusted block")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, str):
        raise PromptTemplateError(
            f"trusted slot {name!r} refuses a plain str; wrap external text with "
            "wrap_untrusted, or pass a StrEnum or a Pydantic model"
        )
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, BaseModel):
        # Escaped so a string field cannot close the `<data>` element.
        return value.model_dump_json().translate(_ESCAPE_ANGLE_BRACKETS)
    raise PromptTemplateError(f"trusted slot {name!r} does not accept type {type(value).__name__}")

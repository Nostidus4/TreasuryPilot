"""LLM-isolated advisory tasks. Every model call goes through `AiAdapter.run`."""

from treasurypilot_worker.agent.adapter import AiAdapter
from treasurypilot_worker.agent.budget import BudgetLedger, InMemoryBudgetLedger, cost_usd_micros
from treasurypilot_worker.agent.config import (
    AiConfig,
    AiTask,
    ModelPrice,
    TaskConfig,
    load_ai_config,
)
from treasurypilot_worker.agent.errors import (
    AiBudgetExceeded,
    AiError,
    AiSchemaError,
    AiTimeout,
    AiToolLimitExceeded,
    AiUnavailable,
)
from treasurypilot_worker.agent.fake import FakeClock, FakeProvider, fake_text, fake_tool_use
from treasurypilot_worker.agent.types import (
    AiResult,
    ContentBlock,
    Message,
    Provider,
    ProviderRequest,
    ProviderResponse,
    StopReason,
    TextBlock,
    Tool,
    ToolCall,
    ToolCallRecord,
    ToolResult,
    ToolSpec,
    Usage,
)

__all__ = [
    "AiAdapter",
    "AiBudgetExceeded",
    "AiConfig",
    "AiError",
    "AiResult",
    "AiSchemaError",
    "AiTask",
    "AiTimeout",
    "AiToolLimitExceeded",
    "AiUnavailable",
    "BudgetLedger",
    "ContentBlock",
    "FakeClock",
    "FakeProvider",
    "InMemoryBudgetLedger",
    "Message",
    "ModelPrice",
    "Provider",
    "ProviderRequest",
    "ProviderResponse",
    "StopReason",
    "TaskConfig",
    "TextBlock",
    "Tool",
    "ToolCall",
    "ToolCallRecord",
    "ToolResult",
    "ToolSpec",
    "Usage",
    "cost_usd_micros",
    "fake_text",
    "fake_tool_use",
    "load_ai_config",
]

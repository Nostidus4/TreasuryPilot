"""AnthropicProvider against a local HTTP stub: request shape, response mapping, real timeouts."""

import json
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import anthropic
import pytest
from pydantic import BaseModel, ConfigDict

from treasurypilot_worker.agent import (
    AiAdapter,
    AiConfig,
    AiTask,
    AiTimeout,
    AiUnavailable,
    InMemoryBudgetLedger,
    Message,
    PromptTemplate,
    ProviderRequest,
    StopReason,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolSpec,
    Usage,
)
from treasurypilot_worker.agent.anthropic_provider import AnthropicProvider

Responder = Callable[[dict[str, object]], tuple[int, dict[str, object]]]


class Stub:
    def __init__(self) -> None:
        self.bodies: list[dict[str, object]] = []
        self.respond: Responder = lambda body: (200, _message([_text('{"answer": "ok"}')]))
        self.delay_s = 0.0


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


@pytest.fixture
def stub() -> Iterator[tuple[Stub, str]]:
    state = Stub()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            state.bodies.append(body)
            time.sleep(state.delay_s)
            status, payload = state.respond(body)
            data = json.dumps(payload).encode()
            try:
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("request-id", "req_stub")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.block_on_close = False
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    yield state, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _text(text: str) -> dict[str, object]:
    return {"type": "text", "text": text}


def _message(content: list[dict[str, object]], stop_reason: str = "end_turn") -> dict[str, object]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_creation_input_tokens": 50,
            "cache_read_input_tokens": 400,
        },
    }


def _provider(base_url: str) -> AnthropicProvider:
    return AnthropicProvider(anthropic.Anthropic(api_key="test-key", base_url=base_url))


def _request(**overrides: object) -> ProviderRequest:
    fields: dict[str, object] = {
        "model": "claude-sonnet-5-5",
        "system": "You answer treasury questions.",
        "messages": (Message("user", (TextBlock("Why?"),)),),
        "tools": (),
        "output_schema": Answer.model_json_schema(),
        "max_output_tokens": 300,
    }
    fields.update(overrides)
    return ProviderRequest(**fields)  # type: ignore[arg-type]


def test_request_uses_structured_output_strict_tools_and_cached_system(
    stub: tuple[Stub, str],
) -> None:
    state, url = stub
    spec = ToolSpec(
        "get_snapshot",
        "Read the snapshot.",
        {
            "type": "object",
            "properties": {"treasury_id": {"type": "string"}},
            "required": ["treasury_id"],
            "additionalProperties": False,
        },
    )
    history = (
        Message("user", (TextBlock("Why?"),)),
        Message("assistant", (ToolCall("t1", "get_snapshot", {"treasury_id": "tr-1"}),)),
        Message("user", (ToolResult("t1", '{"balance": "6000"}'),)),
    )

    _provider(url).complete(_request(tools=(spec,), messages=history), timeout_s=5)

    body = state.bodies[0]
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] == 300
    assert body["system"] == [
        {
            "type": "text",
            "text": "You answer treasury questions.",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    output_config = body["output_config"]
    assert output_config["format"]["type"] == "json_schema"  # type: ignore[index]
    assert output_config["format"]["schema"]["additionalProperties"] is False  # type: ignore[index]
    assert body["tools"][0]["strict"] is True  # type: ignore[index]
    assert body["tools"][0]["name"] == "get_snapshot"  # type: ignore[index]
    messages = body["messages"]
    assert messages[1]["content"][0]["type"] == "tool_use"  # type: ignore[index]
    assert messages[2]["content"][0] == {  # type: ignore[index]
        "type": "tool_result",
        "tool_use_id": "t1",
        "content": '{"balance": "6000"}',
        "is_error": False,
    }


def test_response_maps_text_tool_calls_and_cache_usage(stub: tuple[Stub, str]) -> None:
    state, url = stub
    state.respond = lambda body: (
        200,
        _message(
            [
                _text("Checking."),
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "get_snapshot",
                    "input": {"treasury_id": "tr-1"},
                },
            ],
            stop_reason="tool_use",
        ),
    )

    response = _provider(url).complete(_request(), timeout_s=5)

    assert response.stop_reason is StopReason.TOOL_USE
    assert response.text == "Checking."
    assert response.tool_calls == (ToolCall("toolu_1", "get_snapshot", {"treasury_id": "tr-1"}),)
    assert response.usage == Usage(100, 20, cache_write_tokens=50, cache_read_tokens=400)


def test_assistant_provider_content_is_echoed_verbatim(stub: tuple[Stub, str]) -> None:
    state, url = stub
    first = _provider(url).complete(_request(), timeout_s=5)
    assistant = Message("assistant", (TextBlock("x"),), provider_content=first.provider_content)

    _provider(url).complete(
        _request(messages=(Message("user", (TextBlock("Why?"),)), assistant)), timeout_s=5
    )

    assert state.bodies[1]["messages"][1]["content"] == [  # type: ignore[index]
        {"type": "text", "text": '{"answer": "ok"}'}
    ]


def test_slow_provider_raises_ai_timeout_near_the_given_timeout(stub: tuple[Stub, str]) -> None:
    state, url = stub
    state.delay_s = 2.0

    started = time.monotonic()
    with pytest.raises(AiTimeout):
        _provider(url).complete(_request(), timeout_s=0.2)

    assert time.monotonic() - started < 1.0


def test_adapter_deadline_holds_against_a_real_slow_provider(
    stub: tuple[Stub, str], repo_config: AiConfig
) -> None:
    state, url = stub
    state.delay_s = 2.0
    tasks = dict(repo_config.tasks)
    tasks[AiTask.EXPLAIN] = tasks[AiTask.EXPLAIN].model_copy(update={"timeout_s": 0.3})
    config = repo_config.model_copy(update={"tasks": tasks})
    adapter = AiAdapter(provider=_provider(url), config=config, ledger=InMemoryBudgetLedger())

    started = time.monotonic()
    with pytest.raises(AiTimeout):
        adapter.run(
            AiTask.EXPLAIN,
            org_id="org-1",
            prompt=PromptTemplate(version="t.v1", system="s.", instructions="q").render(),
            output=Answer,
        )

    assert time.monotonic() - started < 1.0


@pytest.mark.parametrize(
    ("status", "retryable"), [(429, True), (529, True), (500, True), (400, False), (401, False)]
)
def test_status_errors_map_to_ai_unavailable(
    stub: tuple[Stub, str], status: int, retryable: bool
) -> None:
    state, url = stub
    state.respond = lambda body: (
        status,
        {"type": "error", "error": {"type": "api_error", "message": "nope"}},
    )

    with pytest.raises(AiUnavailable) as caught:
        _provider(url).complete(_request(), timeout_s=5)

    assert caught.value.retryable is retryable
    assert len(state.bodies) == 1  # the SDK does not retry on its own


def test_unknown_stop_reason_is_unavailable(stub: tuple[Stub, str]) -> None:
    state, url = stub
    state.respond = lambda body: (200, _message([], stop_reason="pause_turn"))

    with pytest.raises(AiUnavailable, match="pause_turn"):
        _provider(url).complete(_request(), timeout_s=5)

import copy
from types import SimpleNamespace

import pytest
from anthropic.types.beta import BetaMessage

from fantasy_gm import chat
from fantasy_gm.analytics.league import load_league
from fantasy_gm.db import session_scope
from fantasy_gm.sync import add_espn_league
from tests.fake_espn import LEAGUE_ID, SEASON


def message(content, stop_reason):
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": chat.MODEL,
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )


class FakeStream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for b in self.msg.content:
            if b.type == "tool_use":
                yield SimpleNamespace(type="content_block_start", content_block=b)
            elif b.type == "text":
                yield SimpleNamespace(type="text", text=b.text)

    def get_final_message(self):
        return self.msg


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return FakeStream(self.responses.pop(0))


@pytest.fixture
def league_id(db):
    return add_espn_league(LEAGUE_ID, SEASON, db)


def test_tool_loop_streams_and_persists(league_id):
    client = FakeClient(
        [
            message(
                [
                    {"type": "thinking", "thinking": "", "signature": "sig"},
                    {"type": "text", "text": "Checking. "},
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "get_team_roster",
                        "input": {"team": "jugg"},
                    },
                ],
                "tool_use",
            ),
            message([{"type": "text", "text": "Juggernaut is stacked."}], "end_turn"),
        ]
    )
    events = list(chat.run_chat(client, league_id, "conv-1", "How good is Juggernaut?"))
    assert [e["type"] for e in events] == ["text", "tool", "text", "done"]
    assert events[1]["label"] == "Reading roster"

    second = client.requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert second[1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig"}
    result = second[2]["content"][0]
    assert result["tool_use_id"] == "tu_1" and not result["is_error"]
    assert '"team": "Juggernaut"' in result["content"]
    req = client.requests[0]
    assert req["model"] == "claude-opus-5" and req["fallbacks"] == "default"
    assert not any("eager_input_streaming" in t for t in req["tools"])

    assert chat.transcript("conv-1") == [
        {"role": "user", "text": "How good is Juggernaut?"},
        {"role": "assistant", "text": "Checking. \n\nJuggernaut is stacked."},
    ]
    # Next turn replays the whole stored conversation.
    client.responses.append(message([{"type": "text", "text": "Sure."}], "end_turn"))
    list(chat.run_chat(client, league_id, "conv-1", "Thanks"))
    assert len(client.requests[2]["messages"]) == 5


def test_bad_tool_input_is_reported_to_model(league_id):
    client = FakeClient(
        [
            message(
                [
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "get_team_roster",
                        "input": {"team": "nobody"},
                    }
                ],
                "tool_use",
            ),
            message([{"type": "text", "text": "Which team?"}], "end_turn"),
        ]
    )
    list(chat.run_chat(client, league_id, "conv-2", "roster?"))
    result = client.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] and "No single team matches" in result["content"]


def test_truncated_tool_call_is_not_run_but_answered(league_id):
    client = FakeClient(
        [
            message(
                [{"type": "tool_use", "id": "tu_9", "name": "find_trades", "input": {}}],
                "max_tokens",
            ),
        ]
    )
    events = list(chat.run_chat(client, league_id, "conv-3", "trades?"))
    assert events[-2]["type"] == "error"
    hist = chat.load_history("conv-3")
    assert hist[-1]["content"][0]["tool_use_id"] == "tu_9"  # history stays valid for the next turn


def test_fallback_boundary_drops_prior_tool_blocks():
    msg = message(
        [
            {"type": "thinking", "thinking": "", "signature": "a"},
            {"type": "text", "text": "partial"},
            {
                "type": "fallback",
                "from": {"model": "claude-opus-5"},
                "to": {"model": "claude-opus-4-8"},
                "trigger": {"type": "refusal", "category": None},
            },
            {"type": "text", "text": "rest"},
        ],
        "end_turn",
    )
    blocks = chat._block_params(msg.content)
    assert [b["type"] for b in blocks] == ["text", "fallback", "text"]
    assert blocks[1]["from"] == {"model": "claude-opus-5"}  # serialized by alias, not from_


@pytest.mark.parametrize("tool", [t.name for t in chat.TOOLS])
def test_every_tool_runs_on_real_data(league_id, tool):
    with session_scope() as s:
        ctx = chat.LeagueContext(load_league(s, league_id))
    args = {
        "evaluate_trade": {"partner": "Middling", "give": ["Bench WR"], "get": ["RB1"]},
        "find_player": {"name": "stud"},
    }.get(tool, {})
    content, is_error = chat.run_tool(ctx, tool, args)
    assert not is_error, content


def test_missing_credentials_reported(league_id):
    class NoKey(FakeClient):
        def _stream(self, **kwargs):
            raise TypeError('"Could not resolve authentication method. Expected one of api_key..."')

    events = list(chat.run_chat(NoKey([]), league_id, "conv-4", "hi"))
    assert events[0]["type"] == "error" and "ANTHROPIC_API_KEY" in events[0]["message"]


def test_tools_are_not_eager_streamed():
    # Eager input streaming skips the API's input validation; with it on, evaluate_trade
    # calls arrived as unparseable JSON and every retry failed the same way.
    assert all("eager_input_streaming" not in t.definition() for t in chat.TOOLS)


def test_evaluate_trade_accepts_comma_separated_names(league_id):
    with session_scope() as s:
        ctx = chat.LeagueContext(load_league(s, league_id))
    content, is_error = chat.run_tool(
        ctx, "evaluate_trade", {"partner": "Juggernaut", "give": "QB, RB1", "get": "WR1"}
    )
    assert not is_error, content
    args = chat.TradeEvalArgs.model_validate({"partner": "x", "give": "A, B", "get": ["C"]})
    assert (args.give, args.get) == (["A", "B"], ["C"])

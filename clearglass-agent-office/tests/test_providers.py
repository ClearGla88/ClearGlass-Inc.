from types import SimpleNamespace

from agent_core.providers import DEFAULT_CLAUDE_MODEL, ClaudeProvider, OfflineProvider, provider_from_env
from policy_engine import ActionRequest
from tests.conftest import make_office


class FakeMessages:
    def __init__(self, reply=None, stop="end_turn", raise_exc=None):
        self.reply, self.stop, self.raise_exc, self.calls = reply, stop, raise_exc, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type="text", text=self.reply)])


def fake_client(**kw):
    messages = FakeMessages(**kw)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_offline_is_the_default():
    assert isinstance(provider_from_env({}), OfflineProvider)


def test_claude_request_shape():
    client, messages = fake_client(reply="Rewritten.")
    p = ClaudeProvider(client=client)
    assert p.rewrite("Draft.", "test") == "Rewritten."
    call = messages.calls[0]
    assert call["model"] == DEFAULT_CLAUDE_MODEL
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"] == {"effort": "medium"}
    assert "<draft>" in call["messages"][0]["content"]


def test_refusal_and_errors_keep_the_template():
    client, _ = fake_client(reply="x", stop="refusal")
    assert ClaudeProvider(client=client).rewrite("Draft.", "t") is None
    client, _ = fake_client(raise_exc=RuntimeError("network"))
    assert ClaudeProvider(client=client).rewrite("Draft.", "t") is None


def test_rewrites_that_invent_figures_are_rejected():
    client, _ = fake_client(reply="Over 73% of Ontario firms were breached in 2025.")
    office = make_office(provider=ClaudeProvider(client=client))
    r = office.perform(
        ActionRequest(
            agent_id="growth.content-writer",
            action_type="content.draft",
            params={
                "posts": [
                    {"topic": "Approval gates", "points": ["Drafts are free"], "next_step": "Add one sign-off step."}
                ]
            },
        )
    )
    post = r.output["artifact"]["posts"][0]
    assert "73%" not in post["text"] and "rewrite rejected" in post["provenance"]

"""The client must auto-drop `seed` when a provider (e.g. Gemini's OpenAI-compat
layer) rejects it, instead of failing every request."""

from types import SimpleNamespace

from bible_bench.config import LlmEndpointConfig
from bible_bench.llm import LlmClient


class _FakeCompletions:
    """Rejects any request that includes `seed` (like Gemini's compat API)."""

    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if "seed" in kwargs:
            raise Exception('400 Invalid JSON payload: Unknown name "seed": Cannot find field.')
        msg = SimpleNamespace(content="In the beginning God created the heavens and the earth.")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=msg)],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=12),
        )


def _client():
    c = LlmClient(LlmEndpointConfig(base_url="x", api_key="k", model="m", label="m"))
    c._client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
    return c


async def test_seed_rejected_is_dropped_and_succeeds():
    c = _client()
    text = await c.complete([{"role": "user", "content": "hi"}], max_tokens=32)
    assert text.startswith("In the beginning")
    assert c._send_seed is False                      # learned to stop sending seed
    fake = c._client.chat.completions
    assert "seed" in fake.calls[0]                     # first try had seed (rejected)
    assert "seed" not in fake.calls[1]                 # retry dropped it
    assert len(fake.calls) == 2                        # no wasted backoff attempts


async def test_seed_kept_when_accepted():
    # A provider that accepts seed: it stays on and is sent.
    c = LlmClient(LlmEndpointConfig(base_url="x", api_key="k", model="m", label="m"))

    class _OK:
        def __init__(self): self.calls = []
        async def create(self, **kwargs):
            self.calls.append(kwargs)
            msg = SimpleNamespace(content="ok")
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)

    ok = _OK()
    c._client = SimpleNamespace(chat=SimpleNamespace(completions=ok))
    await c.complete([{"role": "user", "content": "hi"}])
    assert c._send_seed is True
    assert "seed" in ok.calls[0]

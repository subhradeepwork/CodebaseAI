import io
import json

from app.services import llm as llmmod


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return io.BytesIO(json.dumps(self.payload).encode('utf-8'))
    def __exit__(self, exc_type, exc, tb):
        return False


def test_mlx_plain_string_message(monkeypatch):
    monkeypatch.setattr(llmmod.urllib.request, 'urlopen', lambda *a, **k: FakeResponse({'choices':[{'message':'hello'}]}))
    assert llmmod.LLMClient().chat([{'role':'user','content':'x'}]) == 'hello'


def test_mlx_openai_style_message(monkeypatch):
    monkeypatch.setattr(llmmod.urllib.request, 'urlopen', lambda *a, **k: FakeResponse({'choices':[{'message':{'role':'assistant','content':'hello'}}]}))
    assert llmmod.LLMClient().chat([{'role':'user','content':'x'}]) == 'hello'

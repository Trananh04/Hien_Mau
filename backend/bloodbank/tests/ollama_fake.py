"""Client Ollama giả lập cho test — không gọi mô hình thật. Mô phỏng `client.chat(stream=True)` trả về các mảnh
(chunk) giống SDK `ollama`: message.content / message.tool_calls, mảnh cuối done=True kèm số token."""
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings

# Bật chế độ AI trong test (bộ test mặc định tắt OLLAMA_BASE_URL để không bao giờ gọi mô hình thật)
MODEL = "qwen3:4b-instruct-2507-q4_K_M"
ai_on = override_settings(OLLAMA_BASE_URL="http://ollama-test:11434", OLLAMA_MODEL=MODEL, CHATBOT_USE_LLM=True)


def chunk(content="", tool_calls=None, done=False):
    return SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls), done=done,
                           model=MODEL, prompt_eval_count=120, eval_count=30, total_duration=2_000_000, load_duration=0)


def reply(text):
    """Câu trả lời dạng chữ, chia 2 mảnh + mảnh kết thúc."""
    cut = max(1, len(text) // 2)
    return iter([chunk(text[:cut]), chunk(text[cut:]), chunk(done=True)])


def call(name, args=None):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=args or {}))


def tool_reply(*calls):
    """Lượt mô hình yêu cầu gọi công cụ (không có chữ)."""
    return iter([chunk(tool_calls=list(calls)), chunk(done=True)])


def fake_client(*rounds):
    """rounds: mỗi phần tử là kết quả của 1 lần client.chat — iterator mảnh, hoặc exception để raise."""
    client = mock.Mock()
    client.chat.side_effect = list(rounds)
    return client


def sent_messages(client, n=0):
    return client.chat.call_args_list[n].kwargs["messages"]

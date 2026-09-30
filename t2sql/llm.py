"""Lớp gọi LLM. Mặc định dùng Claude qua Anthropic SDK; có bản giả lập để test offline."""
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass


class LLMError(Exception):
    pass


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0


class BaseLLM:
    def __init__(self):
        self.usage = Usage()
        self._lock = threading.Lock()

    def complete(self, system: str, messages: list[dict], max_tokens: int = 16000,
                 temperature: float | None = None, reasoning: str | None = None) -> str:
        """temperature=None: dùng mặc định của provider. Self-consistency truyền giá trị > 0 để lấy mẫu đa dạng.
        reasoning: ghi đè mức suy nghĩ cho riêng lời gọi này (low / medium / high); None = theo cấu hình chung."""
        raise NotImplementedError

    def _record(self, inp, out, secs):
        with self._lock:
            self.usage.calls += 1
            self.usage.input_tokens += inp
            self.usage.output_tokens += out
            self.usage.seconds += secs


# Model hỗ trợ server-side fallback dạng `fallbacks="default"`.
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
# Model KHÔNG nhận output_config.effort (gửi lên sẽ bị lỗi 400).
NO_EFFORT_PREFIXES = ("claude-haiku", "claude-3", "claude-sonnet-4-5", "claude-sonnet-4-0",
                      "claude-sonnet-4-2", "claude-opus-4-1", "claude-opus-4-0", "claude-opus-4-2")
# Model nhận effort nhưng chưa có mức "xhigh" (tự hạ xuống "high").
NO_XHIGH_PREFIXES = ("claude-opus-4-5", "claude-opus-4-6", "claude-sonnet-4-6")


def _env(name, default=None):
    v = os.environ.get(name, "").strip()
    return v or default


class ClaudeLLM(BaseLLM):
    """Claude qua Anthropic SDK. Cấu hình trong file .env (xem .env.example) hoặc biến môi trường:

      ANTHROPIC_API_KEY   key (hoặc profile từ `ant auth login`)
      ANTHROPIC_BASE_URL  URL API / gateway (SDK tự đọc), mặc định https://api.anthropic.com
      T2SQL_MODEL         mặc định claude-opus-5-5
      T2SQL_EFFORT        low | medium | high | xhigh | max; trống = mặc định của model
      T2SQL_FALLBACKS     "0" để tắt server-side fallback khi model từ chối
      T2SQL_MAX_TOKENS    giới hạn max_tokens mỗi lời gọi
    """

    def __init__(self, model: str | None = None, effort: str | None = None):
        super().__init__()
        import anthropic  # import muộn để test offline không cần SDK
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=4)
        self.model = model or _env("T2SQL_MODEL", "claude-opus-5-5")
        self.effort = self._effort_for_model(effort or _env("T2SQL_EFFORT"))
        self.fallbacks = _env("T2SQL_FALLBACKS", "1") != "0" and self.model in FALLBACK_MODELS
        cap = _env("T2SQL_MAX_TOKENS")
        self.max_tokens_cap = int(cap) if cap else None
        self._lock_opts = threading.Lock()

    def _effort_for_model(self, effort):
        if not effort or self.model.startswith(NO_EFFORT_PREFIXES):
            return None
        if effort == "xhigh" and self.model.startswith(NO_XHIGH_PREFIXES):
            return "high"
        return effort

    def _kwargs(self, system, messages, max_tokens):
        if self.max_tokens_cap:
            max_tokens = min(max_tokens, self.max_tokens_cap)
        kwargs = dict(model=self.model, max_tokens=max_tokens, system=system, messages=messages)
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        if self.fallbacks:
            # Nếu model từ chối vì chính sách an toàn, API tự chạy lại trên model dự phòng.
            kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        return kwargs

    def _drop_optional(self) -> bool:
        """Tắt các tham số tùy chọn (fallback, effort) sau khi model/gateway từ chối. True nếu còn gì để tắt."""
        with self._lock_opts:
            changed = self.fallbacks or self.effort is not None
            self.fallbacks, self.effort = False, None
            return changed

    def complete(self, system, messages, max_tokens=16000, temperature=None, reasoning=None):
        # Các model Claude đời mới (Opus 4.7+, Sonnet 5.x, Fable) trả 400 khi nhận temperature, nên bỏ qua tham số này:
        # self-consistency với Claude sẽ ít đa dạng hơn (chỉ khác nhau do bản chất không tất định của model).
        a = self._anthropic
        t0 = time.perf_counter()
        try:
            try:
                resp = self.client.beta.messages.create(**self._kwargs(system, messages, max_tokens))
            except a.BadRequestError as e:
                # Model cũ / gateway không nhận effort hoặc fallbacks: bỏ chúng và gửi lại một lần.
                if not self._drop_optional():
                    raise
                print(f"[t2sql] {self.model} từ chối tham số tùy chọn ({e.message}); "
                      "gửi lại không kèm effort/fallbacks.", file=sys.stderr)
                resp = self.client.beta.messages.create(**self._kwargs(system, messages, max_tokens))
        except a.AuthenticationError as e:
            raise LLMError("Không xác thực được với Anthropic API. Kiểm tra ANTHROPIC_API_KEY trong .env "
                           "(hoặc chạy `ant auth login`).") from e
        except a.NotFoundError as e:
            raise LLMError(f"Không tìm thấy model '{self.model}' hoặc sai ANTHROPIC_BASE_URL: {e.message}") from e
        except a.BadRequestError as e:
            raise LLMError(f"Yêu cầu không hợp lệ: {e.message}") from e
        except a.RateLimitError as e:
            raise LLMError("Bị giới hạn tốc độ (rate limit), thử lại sau.") from e
        except a.APIStatusError as e:
            raise LLMError(f"Lỗi API ({e.status_code}): {e.message}") from e
        except a.APIConnectionError as e:
            raise LLMError(f"Không kết nối được tới {self.client.base_url}. Kiểm tra ANTHROPIC_BASE_URL.") from e
        except TypeError as e:
            if "authentication" not in str(e):
                raise
            raise LLMError("Chưa có API key. Điền ANTHROPIC_API_KEY trong file .env "
                           "(hoặc chạy `ant auth login`).") from e
        self._record(resp.usage.input_tokens, resp.usage.output_tokens, time.perf_counter() - t0)
        if resp.stop_reason == "refusal":
            raise LLMError("Model từ chối trả lời yêu cầu này.")
        text = "".join(b.text for b in resp.content if b.type == "text")
        if resp.stop_reason == "max_tokens" and not text:
            raise LLMError("Phản hồi bị cắt do chạm max_tokens.")
        return text


class ScriptedLLM(BaseLLM):
    """LLM giả lập: `fn(system, messages) -> str`. Dùng cho unit test và kiểm tra pipeline."""

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.calls = []
        self.temperatures = []
        self.reasoning_levels = []

    def complete(self, system, messages, max_tokens=16000, temperature=None, reasoning=None):
        with self._lock:
            self.calls.append((system, [dict(m) for m in messages]))
            self.temperatures.append(temperature)
            self.reasoning_levels.append(reasoning)
        self._record(0, 0, 0.0)
        return self.fn(system, messages)


_THINK = re.compile(r"<think>.*?</think>|^.*?</think>", re.S)


_CTX_ERR = re.compile(r"context length|context_length|max_tokens|maximum.*tokens|too many tokens", re.I)


class OpenAICompatLLM(BaseLLM):
    """Model tự host qua API chuẩn OpenAI (vLLM, Ollama, LM Studio, gateway Bifrost/LiteLLM...).

    Chỉ dùng thư viện chuẩn. Mặc định dùng streaming (SSE) để chịu được model suy nghĩ lâu:
    kết nối không bị proxy ngắt vì im lặng quá lâu, và thời gian chờ tính theo khoảng lặng giữa hai token.

    Biến môi trường:
      LLM_BASE_URL        ví dụ http://10.100.110.251:30301/v1 (tự thêm /v1 nếu thiếu)
      LLM_API_KEY         key của gateway (có thể trống nếu server không cần)
      T2SQL_MODEL         tên model đúng như /v1/models trả về, ví dụ SDS-AI/softdream
      T2SQL_TEMPERATURE   mặc định 0 (ổn định khi chấm điểm)
      T2SQL_MAX_TOKENS    mặc định 8192; vượt context của model thì tự giảm dần
      T2SQL_STREAM        1 (mặc định) = streaming; 0 = chờ một phản hồi duy nhất
      T2SQL_TIMEOUT       giây chờ token đầu tiên / giữa hai token (streaming), hoặc cả lời gọi (không streaming);
                          mặc định 600
      T2SQL_MAX_WAIT      tổng số giây tối đa cho một lời gọi khi streaming, mặc định 1800
      T2SQL_RETRIES       số lần thử lại khi timeout / 429 / 5xx, mặc định 1
    """

    def __init__(self, model: str | None = None, base_url: str | None = None, api_key: str | None = None):
        super().__init__()
        base = (base_url or _env("LLM_BASE_URL") or _env("ANTHROPIC_BASE_URL") or "http://localhost:8000").rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        self.base_url = base
        self.api_key = api_key or _env("LLM_API_KEY") or _env("ANTHROPIC_API_KEY")
        self.model = model or _env("T2SQL_MODEL")
        if not self.model:
            raise LLMError("Chưa đặt T2SQL_MODEL trong .env (tên model như /v1/models trả về).")
        self.effort = None
        self.temperature = float(_env("T2SQL_TEMPERATURE", "0"))
        self.max_tokens_cap = int(_env("T2SQL_MAX_TOKENS", "8192"))
        self.stream = _env("T2SQL_STREAM", "1") != "0"
        self.timeout = float(_env("T2SQL_TIMEOUT", "600"))
        self.max_wait = float(_env("T2SQL_MAX_WAIT", "1800"))
        self.retries = int(_env("T2SQL_RETRIES", "1"))
        # Tham số riêng của server, gộp vào mọi request. Ví dụ tắt suy nghĩ trên vLLM (Qwen3...):
        #   T2SQL_EXTRA_BODY={"chat_template_kwargs": {"enable_thinking": false}}
        extra = _env("T2SQL_EXTRA_BODY")
        try:
            self.extra_body = json.loads(extra) if extra else {}
        except json.JSONDecodeError as e:
            raise LLMError(f"T2SQL_EXTRA_BODY không phải JSON hợp lệ: {e}") from e
        # Bật/tắt suy nghĩ (reasoning) qua tham số chuẩn reasoning_effort (Bifrost chuyển tiếp xuống model).
        #   T2SQL_REASONING=off -> reasoning_effort="none";  low|medium|high -> mức tương ứng; trống = mặc định model
        reasoning = (_env("T2SQL_REASONING") or "").lower()
        if reasoning in ("off", "0", "false", "none", "no"):
            self.extra_body.setdefault("reasoning_effort", "none")
        elif reasoning in ("low", "medium", "high"):
            self.extra_body.setdefault("reasoning_effort", reasoning)
        self.reasoning = self.extra_body.get("reasoning_effort", "mặc định")
        self._local = threading.local()

    # Callback tiến độ cho giao diện: fn(phase, n_chunks, elapsed_s), phase = "thinking" | "answer".
    # Lưu theo luồng để nhiều phiên Streamlit dùng chung một pipeline không lẫn của nhau.
    def set_progress(self, fn):
        self._local.progress = fn

    def _progress(self, phase, n, t0):
        fn = getattr(self._local, "progress", None)
        if fn:
            try:
                fn(phase, n, time.perf_counter() - t0)
            except Exception:
                pass

    def _request(self, payload):
        import urllib.request
        headers = {"Content-Type": "application/json"}
        if payload.get("stream"):
            headers["Accept"] = "text/event-stream"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return urllib.request.Request(self.base_url + "/chat/completions",
                                      data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

    def _read_stream(self, resp, t0):
        """Đọc SSE; trả (content, finish_reason, usage). Socket timeout = khoảng lặng tối đa giữa hai dòng."""
        content, finish, usage, n = [], None, {}, 0
        for raw in resp:
            if time.perf_counter() - t0 > self.max_wait:
                raise TimeoutError(f"vượt T2SQL_MAX_WAIT={self.max_wait:g}s")
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            if chunk.get("error"):
                raise LLMError(f"Server báo lỗi giữa chừng: {str(chunk['error'])[:300]}")
            usage = chunk.get("usage") or usage
            for ch in chunk.get("choices") or []:
                delta = ch.get("delta") or {}
                if delta.get("reasoning_content") or delta.get("reasoning"):
                    n += 1
                    self._progress("thinking", n, t0)
                if delta.get("content"):
                    content.append(delta["content"])
                    n += 1
                    self._progress("answer", n, t0)
                finish = ch.get("finish_reason") or finish
        return "".join(content), finish, usage

    def _call(self, payload):
        import urllib.error
        import urllib.request
        t0 = time.perf_counter()
        last = None
        attempt = 0
        while attempt <= self.retries:
            try:
                with urllib.request.urlopen(self._request(payload), timeout=self.timeout) as r:
                    if payload.get("stream"):
                        return self._read_stream(r, t0)
                    data = json.loads(r.read().decode("utf-8"))
                    choice = (data.get("choices") or [{}])[0]
                    return ((choice.get("message") or {}).get("content") or "", choice.get("finish_reason"),
                            data.get("usage") or {})
            except urllib.error.HTTPError as e:
                detail = e.read()[:500].decode("utf-8", "replace")
                if e.code in (401, 403):
                    raise LLMError(f"Gateway từ chối key ({e.code}). Kiểm tra LLM_API_KEY trong .env.") from e
                if e.code == 404:
                    raise LLMError(f"Không tìm thấy {self.base_url} hoặc model '{self.model}' (404): {detail}") from e
                if e.code == 400 and _CTX_ERR.search(detail) and payload["max_tokens"] > 1024:
                    # prompt + max_tokens vượt context của model: giảm max_tokens rồi thử lại (không tính là retry)
                    payload["max_tokens"] = max(1024, payload["max_tokens"] // 2)
                    self.max_tokens_cap = payload["max_tokens"]
                    print(f"[t2sql] vượt context của model, giảm max_tokens xuống {payload['max_tokens']}",
                          file=sys.stderr)
                    continue
                if e.code == 400 and payload.get("stream_options"):
                    payload.pop("stream_options")   # server không nhận stream_options
                    continue
                if e.code not in (408, 429) and e.code < 500:
                    raise LLMError(f"Yêu cầu không hợp lệ ({e.code}): {detail}") from e
                last = LLMError(f"Lỗi server ({e.code}): {detail}")
            except (TimeoutError, OSError) as e:  # URLError, socket.timeout, ConnectionError đều là OSError
                what = "token tiếp theo" if payload.get("stream") else "phản hồi"
                last = LLMError(f"Không nhận được {what} từ {self.base_url} sau {self.timeout:g}s "
                                f"({type(e).__name__}: {e}). Model có thể đang quá tải; tăng T2SQL_TIMEOUT nếu cần.")
            attempt += 1
            if attempt <= self.retries:
                time.sleep(3 * attempt)
        raise last

    def complete(self, system, messages, max_tokens=16000, temperature=None, reasoning=None):
        payload = {"model": self.model, "messages": [{"role": "system", "content": system}] + messages,
                   "max_tokens": min(max_tokens, self.max_tokens_cap),
                   "temperature": self.temperature if temperature is None else temperature,
                   "stream": self.stream}
        if self.stream:
            payload["stream_options"] = {"include_usage": True}
        payload.update(self.extra_body)
        if reasoning:
            payload["reasoning_effort"] = reasoning
        t0 = time.perf_counter()
        text, finish, usage = self._call(payload)
        self._record(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), time.perf_counter() - t0)
        text = _THINK.sub("", text).strip()   # model suy luận (Qwen3, DeepSeek-R1...) có thể kèm <think>
        if not text and finish == "length":
            raise LLMError("Model dùng hết max_tokens cho phần suy nghĩ mà chưa trả lời. Tăng T2SQL_MAX_TOKENS.")
        if not text:
            raise LLMError("Model trả về câu trả lời rỗng.")
        return text


def default_llm() -> BaseLLM:
    """T2SQL_PROVIDER = openai (model tự host) | anthropic (Claude). Trống: tự chọn theo tên model."""
    provider = (_env("T2SQL_PROVIDER") or "").lower()
    if not provider:
        provider = "anthropic" if (_env("T2SQL_MODEL") or "claude").startswith("claude") else "openai"
    if provider in ("openai", "vllm", "selfhost", "local"):
        return OpenAICompatLLM()
    return ClaudeLLM()

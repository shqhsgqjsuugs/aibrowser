"""LLM 客户端：调用 OpenAI 兼容 Chat Completions 接口。"""
from __future__ import annotations
import os
from typing import Optional


class LLMConfigError(Exception):
    """LLM 配置缺失错误。"""


class LLMClient:
    """OpenAI 兼容 Chat Completions 客户端。

    通过环境变量配置：
        OPENAI_API_KEY  : API 密钥（必需）
        OPENAI_BASE_URL : 接口地址（可选，默认 https://api.openai.com/v1）
        OPENAI_MODEL    : 模型名（可选，默认 gpt-4o-mini）
        OPENAI_TIMEOUT  : 超时秒数（可选，默认 60）

    未配置 OPENAI_API_KEY 时，构造不报错；调用 generate() 时抛 LLMConfigError。
    这样 REPL 模式无需配置即可使用。
    """

    def __init__(self, model: Optional[str] = None):
        self.api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.timeout = float(os.environ.get("OPENAI_TIMEOUT", "60"))
        self._client = None  # 懒加载

    @property
    def is_configured(self) -> bool:
        """是否已配置 API Key。"""
        return bool(self.api_key)

    def _ensure_client(self):
        """懒加载 OpenAI 客户端，未配置时抛 LLMConfigError。"""
        if not self.is_configured:
            raise LLMConfigError(
                "未配置 OPENAI_API_KEY 环境变量。请设置后重试，例如：\n"
                '  set OPENAI_API_KEY=sk-...\n'
                "或在 REPL/交互模式下使用。"
            )
        if self._client is None:
            # 优先使用 openai SDK（若安装）
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    timeout=self.timeout,
                )
            except ImportError:
                # 回退到 urllib 请求，避免强制依赖 openai SDK
                self._client = _UrllibClient(self.api_key, self.base_url, self.timeout)
        return self._client

    def generate(self, prompt: str, system: Optional[str] = None, temperature: float = 0.2) -> str:
        """调用 LLM 生成文本。

        Args:
            prompt: 用户提示词。
            system: 系统提示词，可选。
            temperature: 采样温度。
        Returns:
            生成的文本。
        Raises:
            LLMConfigError: 未配置 API Key。
            Exception: 接口调用失败。
        """
        client = self._ensure_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
        ).choices[0].message.content


class _UrllibClient:
    """urllib 实现的 OpenAI 兼容客户端回退方案。"""

    def __init__(self, api_key, base_url, timeout):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.chat = self._Chat(self)

    class _Chat:
        def __init__(self, parent):
            self.completions = self._Completions(parent)

        class _Completions:
            def __init__(self, parent):
                self.parent = parent

            def create(self, model, messages, temperature=0.2, **kw):
                import json
                import urllib.request
                import urllib.error
                url = f"{self.parent.base_url}/chat/completions"
                payload = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, method="POST")
                req.add_header("Authorization", f"Bearer {self.parent.api_key}")
                req.add_header("Content-Type", "application/json")
                try:
                    with urllib.request.urlopen(req, timeout=self.parent.timeout) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                except urllib.error.HTTPError as e:
                    err_body = e.read().decode("utf-8", errors="replace")
                    raise Exception(f"LLM 接口 HTTP {e.code}: {err_body}") from None
                content = body["choices"][0]["message"]["content"]
                return _Resp(content)


class _Resp:
    """模拟 openai SDK 的响应对象。"""

    def __init__(self, content):
        # 构造 choices[0].message.content 访问链
        self.choices = [
            type("C", (), {"message": type("M", (), {"content": content})()})()
        ]

"""
LLM 客户端封装 v7.0

使用 OpenAI 兼容接口对接 DeepSeek。
只负责 API 调用，不感知 prompt 结构和针法业务逻辑。
"""

import os
import time
import traceback
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from config import LLM_CONFIG
from utils.logger import logger

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI library not installed. Run: pip install openai")


@dataclass
class LLMResponse:
    success: bool
    content: str
    error: Optional[str] = None
    latency_ms: float = 0.0
    model: Optional[str] = None
    usage: Optional[Dict] = None


class LLMClient:
    """
    DeepSeek / OpenAI 兼容客户端。

    使用方式：
        client = LLMClient()
        response = client.chat(messages)
        print(response.content)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        if not OPENAI_AVAILABLE:
            raise ImportError("请先安装 openai：pip install openai")

        self.api_key = (
            api_key
            or os.getenv("DEEPSEEK_API_KEY")
            or LLM_CONFIG.get("api_key")
        )
        if not self.api_key:
            raise ValueError(
                "未找到 API Key。请设置环境变量 DEEPSEEK_API_KEY 或在 config.py 中配置。"
            )

        self.base_url = base_url or LLM_CONFIG.get("base_url", "https://api.deepseek.com")
        self.default_model = default_model or LLM_CONFIG.get("default_model", "deepseek-chat")
        self.timeout = timeout or LLM_CONFIG.get("timeout", 30)

        retry_cfg = LLM_CONFIG.get("retry", {})
        self.max_attempts = retry_cfg.get("max_attempts", 3)
        self.backoff_factor = retry_cfg.get("backoff_factor", 2)

        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
        )

        logger.info(f"LLMClient ready | model={self.default_model} | url={self.base_url}")

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        **kwargs,
    ) -> LLMResponse:
        """
        发送 chat 请求，带自动重试。

        Args:
            messages:    消息列表 [{"role": "...", "content": "..."}]
            model:       模型名称，默认使用 default_model
            temperature: 温度，默认 0.3（结构化输出用低温度）
            max_tokens:  最大输出 token 数

        Returns:
            LLMResponse，调用方直接读 response.content
        """
        model = model or self.default_model

        for attempt in range(self.max_attempts):
            try:
                t0 = time.time()

                raw = self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )

                latency_ms = (time.time() - t0) * 1000
                content = raw.choices[0].message.content.strip()

                usage = None
                if hasattr(raw, "usage") and raw.usage:
                    usage = {
                        "prompt_tokens": raw.usage.prompt_tokens,
                        "completion_tokens": raw.usage.completion_tokens,
                        "total_tokens": raw.usage.total_tokens,
                    }

                logger.debug(
                    f"LLM ok | {latency_ms:.0f}ms | "
                    f"tokens={usage['total_tokens'] if usage else 'N/A'} | "
                    f"preview={content[:80]!r}"
                )

                return LLMResponse(
                    success=True,
                    content=content,
                    latency_ms=latency_ms,
                    model=model,
                    usage=usage,
                )

            except Exception as e:
                logger.warning(f"LLM attempt {attempt + 1}/{self.max_attempts} failed: {e}")
                logger.debug(traceback.format_exc())

                if attempt < self.max_attempts - 1:
                    sleep = self.backoff_factor ** attempt
                    logger.info(f"Retry in {sleep}s...")
                    time.sleep(sleep)
                else:
                    return LLMResponse(
                        success=False,
                        content="",
                        error=str(e),
                        model=model,
                    )

        return LLMResponse(
            success=False,
            content="",
            error="max retries exceeded",
            model=model,
        )

    def list_models(self) -> List[str]:
        try:
            return [m.id for m in self._client.models.list().data]
        except Exception as e:
            logger.error(f"list_models failed: {e}")
            return ["deepseek-chat", "deepseek-coder"]
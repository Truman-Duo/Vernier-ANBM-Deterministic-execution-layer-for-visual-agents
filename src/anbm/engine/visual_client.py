import logging
import os

import httpx

from anbm.adapter.base import VisualClientNotConfiguredError

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 1024


class VisualClient:
    """调用 Anthropic Messages API 进行截图视觉分析。"""

    def __init__(self, api_key: str = None, model: str = DEFAULT_MODEL):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model

    async def analyze(self, screenshot_b64: str, error_context: str) -> str:
        if not self.api_key:
            raise VisualClientNotConfiguredError(
                "ANTHROPIC_API_KEY 未设置，无法调用视觉模型"
            )

        payload = {
            "model": self.model,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": screenshot_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": error_context,
                        },
                    ],
                }
            ],
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")

        logger.info("VisualClient.analyze() 返回 %d 字符", len(text))
        return text

    async def analyze_text(self, prompt: str) -> str:
        """
        纯文本调用，不需要截图。
        复用现有 httpx client 和 API 端点。
        max_tokens=200，selector 不需要长回复。
        """
        if not self.api_key:
            raise VisualClientNotConfiguredError(
                "ANTHROPIC_API_KEY 未设置，无法调用模型"
            )

        payload = {
            "model": self.model,
            "max_tokens": 200,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")

        logger.info("VisualClient.analyze_text() 返回 %d 字符", len(text))
        return text

"""
ANBM Python 客户端 SDK。

同步和异步两种客户端，适合脚本、测试和 Agent 框架集成。

用法：
    from anbm.client import ANBMClient

    client = ANBMClient()
    result = client.browse("https://news.ycombinator.com/news", adapter_hint="hackernews")
    print(result["data"]["stories"][0]["title"])
"""

import httpx


class ANBMError(Exception):
    """ANBM 客户端基础异常。"""


class ANBMConnectionError(ANBMError):
    """连接错误（网络不可达、服务未启动、非预期 HTTP 状态）。"""


class ANBMSessionNotFound(ANBMError):
    """Session 不存在。"""


class ANBMActionRejected(ANBMError):
    """操作被拒绝（session 忙碌、状态不允许等）。"""


class ANBMClient:
    """同步客户端，适合脚本和测试。"""

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def browse(
        self,
        url: str,
        adapter_hint: str = None,
        session_id: str = None,
    ) -> dict:
        body = {"url": url}
        if adapter_hint:
            body["adapter_hint"] = adapter_hint
        if session_id:
            body["session_id"] = session_id
        return self._request("POST", "/browse", json=body)

    def act(self, session_id: str, action: str, params: dict = None) -> dict:
        return self._request(
            "POST", "/act",
            json={"session_id": session_id, "action": action, "params": params or {}},
        )

    def get_session(self, session_id: str) -> dict:
        return self._request("GET", f"/session/{session_id}")

    def delete_session(self, session_id: str) -> dict:
        return self._request("DELETE", f"/session/{session_id}")

    def health(self, adapter_id: str) -> dict:
        return self._request("GET", f"/health/adapter/{adapter_id}")

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            resp = self._client.request(method, self.base_url + path, **kwargs)
        except httpx.RequestError as e:
            raise ANBMConnectionError(f"连接失败: {e}") from e

        if resp.status_code == 404:
            raise ANBMSessionNotFound(resp.text)
        if resp.status_code == 409:
            raise ANBMActionRejected(resp.text)
        if resp.is_error:
            raise ANBMConnectionError(f"HTTP {resp.status_code}: {resp.text}")

        return resp.json()

    def close(self):
        self._client.close()


class AsyncANBMClient:
    """异步客户端，适合 Agent 框架集成。"""

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def browse(
        self,
        url: str,
        adapter_hint: str = None,
        session_id: str = None,
    ) -> dict:
        body = {"url": url}
        if adapter_hint:
            body["adapter_hint"] = adapter_hint
        if session_id:
            body["session_id"] = session_id
        return await self._request("POST", "/browse", json=body)

    async def act(self, session_id: str, action: str, params: dict = None) -> dict:
        return await self._request(
            "POST", "/act",
            json={"session_id": session_id, "action": action, "params": params or {}},
        )

    async def get_session(self, session_id: str) -> dict:
        return await self._request("GET", f"/session/{session_id}")

    async def delete_session(self, session_id: str) -> dict:
        return await self._request("DELETE", f"/session/{session_id}")

    async def health(self, adapter_id: str) -> dict:
        return await self._request("GET", f"/health/adapter/{adapter_id}")

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            resp = await self._client.request(method, self.base_url + path, **kwargs)
        except httpx.RequestError as e:
            raise ANBMConnectionError(f"连接失败: {e}") from e

        if resp.status_code == 404:
            raise ANBMSessionNotFound(resp.text)
        if resp.status_code == 409:
            raise ANBMActionRejected(resp.text)
        if resp.is_error:
            raise ANBMConnectionError(f"HTTP {resp.status_code}: {resp.text}")

        return resp.json()

    async def close(self):
        await self._client.aclose()

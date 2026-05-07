"""
MCP stdio server — exposes ANBM operations as MCP tools.

Compatible with Claude Desktop / Claude Code MCP protocol.
Directly calls FSMEngine methods (no HTTP self-dependency).
"""

import json
import logging
import sys

from anbm.engine.fsm import FSMEngine

logger = logging.getLogger(__name__)

fsm = FSMEngine()

TOOLS = [
    {
        "name": "anbm_browse",
        "description": "导航到 URL 并提取结构化数据，返回当前状态和页面内容",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "session_id": {
                    "type": "string",
                    "description": "可选，复用已有 session",
                },
                "adapter_hint": {
                    "type": "string",
                    "description": "可选，指定 adapter",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "anbm_act",
        "description": "在当前 session 执行一个操作",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "action": {"type": "string"},
                "params": {"type": "object"},
            },
            "required": ["session_id", "action"],
        },
    },
    {
        "name": "anbm_session",
        "description": "查询 session 状态、历史和 retry 统计",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
            },
            "required": ["session_id"],
        },
    },
]

SERVER_INFO = {
    "protocolVersion": "2024-11-05",
    "capabilities": {"tools": {}},
    "serverInfo": {"name": "anbm-mcp", "version": "1.0.0"},
}


async def handle_tool_call(name: str, arguments: dict) -> dict:
    """Execute a tool and return the MCP content result."""
    try:
        if name == "anbm_browse":
            url = arguments["url"]
            session_id = arguments.get("session_id")
            adapter_hint = arguments.get("adapter_hint")

            if session_id:
                result = await fsm.browse(session_id, url)
            else:
                result = await fsm.create_session(
                    url, adapter_hint=adapter_hint
                )
                if "error" not in result:
                    browse_result = await fsm.browse(
                        result["session_id"], url
                    )
                    result.update(browse_result)

        elif name == "anbm_act":
            result = await fsm.act(
                arguments["session_id"],
                arguments["action"],
                params=arguments.get("params", {}),
            )

        elif name == "anbm_session":
            session = await fsm.session_store.get(arguments["session_id"])
            result = {
                "session_id": session.session_id,
                "adapter": session.adapter_id,
                "adapter_version": session.adapter_version,
                "current_state": session.current_state,
                "session_suspended": session.session_suspended,
                "state_history": session.state_history,
                "retry_stats": session.retry_stats,
                "created_at": session.created_at.isoformat(),
                "last_action_at": session.last_action_at.isoformat(),
            }

        else:
            return _mcp_error(-32601, f"Unknown tool: {name}")

        return _mcp_result(result)

    except Exception as e:
        logger.exception("Tool call failed: %s", name)
        return _mcp_error(-32603, str(e))


def _mcp_result(data: dict) -> dict:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(data, ensure_ascii=False, default=str),
            }
        ],
        "isError": False,
    }


def _mcp_error(code: int, message: str) -> dict:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {"error": message}, ensure_ascii=False
                ),
            }
        ],
        "isError": True,
    }


async def handle_request(request: dict) -> dict | None:
    """Handle one JSON-RPC request/notification."""
    method = request.get("method")
    rid = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": SERVER_INFO}

    if method == "notifications/initialized":
        return None

    if method == "notifications/cancelled":
        return None

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        result = await handle_tool_call(
            params.get("name", ""), params.get("arguments", {})
        )
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    return {
        "jsonrpc": "2.0",
        "id": rid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


async def read_stdin_line() -> str:
    """Read one line from stdin via executor (works on Windows)."""
    loop = asyncio.get_event_loop()
    line = await loop.run_in_executor(None, sys.stdin.readline)
    return line


async def main():
    """Main loop: read JSON-RPC from stdin, write responses to stdout."""
    while True:
        line = await read_stdin_line()
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = await handle_request(request)
        if response is not None:
            payload = json.dumps(response, ensure_ascii=False)
            sys.stdout.write(payload + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main())

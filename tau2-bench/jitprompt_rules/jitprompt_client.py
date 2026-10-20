"""Minimal synchronous MCP client for jitprompt (JSON-RPC over streamable HTTP).

tau2 calls tools synchronously from worker threads, so this speaks the MCP
protocol directly with httpx instead of the async `mcp` SDK: initialize →
notifications/initialized → tools/list | tools/call. Responses may come back
as JSON or as an SSE stream; both are handled. One session per client; create
one client per thread (see `for_tier`).
"""

import itertools
import json
import os
import threading
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

MCP_URL = os.environ.get("JITPROMPT_MCP_URL", "https://app.jitprompt.com/mcp")
PROTOCOL_VERSION = "2025-06-18"
DEFAULT_CLIENT_NAME = "tau2-jitprompt-bench"
PINS_HEADER = "# Core procedures (always apply)"  # jitprompt >= 1.3.1 pinned-docs block


class MCPError(RuntimeError):
    pass


class JitpromptMCP:
    def __init__(self, api_key: str, url: str = MCP_URL, client_name: str = DEFAULT_CLIENT_NAME):
        self.url = url
        self.client_name = client_name
        self.http = httpx.Client(
            timeout=httpx.Timeout(60, connect=15),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        self._ids = itertools.count(1)
        self.session_id: str | None = None
        self.server_info: dict = {}
        self.instructions: str | None = None  # initialize result.instructions (pinned docs, >= 1.3.1)
        self.connects = 0  # each connect is a new MCP session: the server re-sends pins once per session

    def _post(self, payload: dict) -> dict | None:
        headers = {}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
        resp = self.http.post(self.url, json=payload, headers=headers)
        if resp.status_code == 404 and self.session_id:
            raise SessionExpired()
        if resp.is_error:
            raise MCPError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        if sid := resp.headers.get("mcp-session-id"):
            self.session_id = sid
        if "id" not in payload:  # notification
            return None
        if resp.headers.get("content-type", "").startswith("text/event-stream"):
            for line in resp.text.splitlines():
                if line.startswith("data:"):
                    msg = json.loads(line[5:].strip())
                    if msg.get("id") == payload["id"]:
                        return msg
            raise MCPError("no response in SSE stream")
        return resp.json()

    def _request(self, method: str, params: dict | None = None) -> dict:
        msg = self._post({"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or {}})
        if "error" in msg:
            raise MCPError(str(msg["error"]))
        return msg["result"]

    def connect(self):
        self.session_id = None
        result = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": self.client_name, "version": "1"},
        })
        self.server_info = {"serverInfo": result.get("serverInfo"), "protocolVersion": result.get("protocolVersion")}
        self.instructions = result.get("instructions")
        self.connects += 1
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def list_tools(self) -> list[dict]:
        return self._with_retry(lambda: self._request("tools/list")["tools"])

    def call_tool(self, name: str, arguments: dict) -> str:
        def call():
            result = self._request("tools/call", {"name": name, "arguments": arguments})
            text = "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
            if result.get("isError"):
                return f"Error: {text}"
            return text

        return self._with_retry(call)

    def _with_retry(self, fn):
        for attempt in range(5):
            try:
                if self.session_id is None:
                    self.connect()
                return fn()
            except SessionExpired:
                self.session_id = None
            except (httpx.TransportError, MCPError) as e:
                if attempt == 4:
                    raise
                self.session_id = None
                time.sleep(2**attempt)
        raise MCPError("retries exhausted")


class SessionExpired(Exception):
    pass


_local = threading.local()


def new_client(tier: str, client_name: str = DEFAULT_CLIENT_NAME) -> JitpromptMCP:
    """A fresh client (= a new MCP session once it connects) for the tier's namespace. Used once
    per conversation by arms where session state matters (1.3.1 delivers pins once per session)."""
    key = os.environ.get(f"JITPROMPT_KEY_RULES_{tier}")
    if not key:
        raise MCPError(f"JITPROMPT_KEY_RULES_{tier} not set")
    return JitpromptMCP(key, client_name=client_name)


def for_tier(tier: str) -> JitpromptMCP:
    """A connected client for the tier's namespace, one per thread (shared across the conversations
    a worker thread runs; fine where server-side session state doesn't matter)."""
    clients = getattr(_local, "clients", None)
    if clients is None:
        clients = _local.clients = {}
    if tier not in clients:
        key = os.environ.get(f"JITPROMPT_KEY_RULES_{tier}")
        if not key:
            raise MCPError(f"JITPROMPT_KEY_RULES_{tier} not set")
        clients[tier] = JitpromptMCP(key).connect()
    return clients[tier]

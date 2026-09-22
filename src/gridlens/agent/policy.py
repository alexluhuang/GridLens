from __future__ import annotations

import ipaddress
import json
import socket
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class AgentError(ValueError):
    def __init__(self, code: str, remedy: str) -> None:
        super().__init__(remedy)
        self.code = code


def local_endpoint(url: str) -> str:
    """Validate and pin a loopback Ollama origin, before sending any data."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port or 11434
        if (
            parts.scheme != "http" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path.rstrip("/") not in ("", "/v1")
        ):
            raise ValueError
        addresses = {item[4][0] for item in socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(address).is_loopback for address in addresses):
            raise ValueError
        address = sorted(addresses, key=lambda item: (":" in item, item))[0]
        host = f"[{address}]" if ":" in address else address
        return f"http://{host}:{port}"
    except (ValueError, OSError) as exc:
        raise AgentError("LOCAL_ENDPOINT_REQUIRED", "Use a loopback Ollama URL, such as http://127.0.0.1:11434.") from exc


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AgentError("ENDPOINT_REDIRECT", "Ollama must answer directly on loopback without redirects.")


def ollama_json(endpoint: str, path: str, body: dict | None = None) -> dict:
    origin = local_endpoint(endpoint)
    request = Request(
        origin + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=5) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except AgentError:
        raise
    except (OSError, ValueError) as exc:
        raise AgentError("OLLAMA_UNAVAILABLE", "Start Ollama locally (ollama serve), then refresh the Agent tab.") from exc


def verify_model(endpoint: str, model: str) -> None:
    info = ollama_json(endpoint, "/api/show", {"model": model})
    if info.get("remote_host") or info.get("remote_model") or "cloud" in model.lower().split(":")[-1]:
        raise AgentError("REMOTE_MODEL_BLOCKED", "Choose an installed local model. Ollama cloud models are disabled.")
    if "tools" not in info.get("capabilities", []):
        raise AgentError("TOOLS_UNSUPPORTED", "Choose an Ollama model that supports tool calls.")

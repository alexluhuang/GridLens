"""Route classification and the hosted-provider gate.

Everything here answers one question before any project data moves: is the inference this session would
use actually local? `local_endpoint` resolves the endpoint and accepts it only when every resolved address
is loopback, and `verify_model` rejects an Ollama model that reports a remote host or a cloud tag. The
hosted gate at the bottom is separate: it governs runtimes that are remote by definition, and it stays
closed unless an operator opens it deliberately.
"""
from __future__ import annotations

import ipaddress
import json
import os
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


HOSTED_GATE_ENV = "GRIDLENS_ALLOW_HOSTED_AGENT"
HOSTED_DISABLED_REMEDY = (
    "Hosted inference is disabled in this deployment. CONTRIBUTING.md and docs/security_ceii.md restrict "
    "GridLens to local-only analysis, so project-derived data must not reach an online model. Authorizing a "
    "hosted runtime is a documented governance decision, not a source change."
)


def hosted_authorization() -> str:
    """Return the authorization level for hosted runtimes: "" (none), "proven", or "all".

    The gate is an explicit operator action rather than a GUI preference, so an ordinary feature change
    cannot weaken the local-only rule by accident. "all" additionally permits a runtime whose tool
    isolation GridLens has not been able to prove, and exists only for adapter development.
    """
    value = os.environ.get(HOSTED_GATE_ENV, "").strip().lower()
    return {"1": "proven", "true": "proven", "yes": "proven", "proven": "proven", "unsafe-all": "all"}.get(value, "")


def require_hosted_authorization(provider: str, isolation_proven: bool = True) -> None:
    level = hosted_authorization()
    if not level:
        raise AgentError("HOSTED_DISABLED", HOSTED_DISABLED_REMEDY)
    if not isolation_proven and level != "all":
        raise AgentError(
            "ISOLATION_UNPROVEN",
            f"GridLens cannot prove that the {provider} CLI exposes only GridLens tools, so it stays disabled "
            "even where hosted inference is authorized. Choose a runtime whose tool surface is verifiable.",
        )

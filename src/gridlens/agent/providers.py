"""The runtime provider registry.

This is the seam that keeps the feature model-agnostic. Everything above it -- the session store, the
controller, the tool service, the MCP server, and the Agent tab -- is written against a provider id and
the RuntimeAdapter protocol. Adding a runtime means adding one module and one row here; it does not touch
the tool layer, the audit format, the session format, or the GUI.

Descriptors carry the facts the GUI needs in order to render one provider correctly without knowing which
provider it is: whether installed models can be enumerated from an endpoint or must be named by the user,
whether an endpoint field applies, whether signing in is a thing for this runtime, and whether the route
is local or remote.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib

from gridlens.agent.policy import AgentError


@dataclass(frozen=True)
class ProviderDescriptor:
    provider: str
    label: str
    route: str
    enumerates_models: bool
    needs_endpoint: bool
    requires_login: bool
    module: str
    adapter: str

    @property
    def local(self) -> bool:
        return self.route == "loopback_only"


DESCRIPTORS = (
    ProviderDescriptor(
        "hermes", "Hermes Agent + local Ollama", "loopback_only",
        enumerates_models=True, needs_endpoint=True, requires_login=False,
        module="gridlens.agent.hermes", adapter="HermesAdapter",
    ),
    ProviderDescriptor(
        "claude", "Claude Code (hosted)", "remote",
        enumerates_models=False, needs_endpoint=False, requires_login=True,
        module="gridlens.agent.claude_code", adapter="ClaudeCodeAdapter",
    ),
    ProviderDescriptor(
        "codex", "Codex CLI (hosted)", "remote",
        enumerates_models=False, needs_endpoint=False, requires_login=True,
        module="gridlens.agent.codex", adapter="CodexAdapter",
    ),
)

PROVIDER_IDS = frozenset(item.provider for item in DESCRIPTORS)
DEFAULT_PROVIDER = DESCRIPTORS[0].provider


def descriptor(provider: str) -> ProviderDescriptor:
    for item in DESCRIPTORS:
        if item.provider == provider:
            return item
    raise AgentError("UNKNOWN_RUNTIME", "Select a runtime that this GridLens build supports.")


def route_for(provider: str) -> str:
    return descriptor(provider).route


def create_adapter(provider: str, endpoint: str = ""):
    """Instantiate an adapter. Imported lazily so one runtime's dependencies cannot break the others."""
    item = descriptor(provider)
    try:
        module = importlib.import_module(item.module)
        factory = getattr(module, item.adapter)
    except (ImportError, AttributeError) as exc:
        raise AgentError("RUNTIME_UNAVAILABLE", f"The {item.label} adapter is not available in this build.") from exc
    return factory(endpoint) if item.needs_endpoint else factory()

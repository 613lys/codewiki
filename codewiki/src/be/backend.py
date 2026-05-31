"""LLMBackend - abstraction for CodeWiki LLM tasks.

CodeWiki has two LLM call shapes:

* a synchronous single-shot completion (clustering, parent / repo overviews)
* a per-module documentation task

The maintained implementation is :class:`IDEBridgeBackend`, which writes
task/result files for an external AI IDE. No API key or local LLM wrapper is
required.

Provider selection happens in one place: :func:`get_backend`.
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from codewiki.src.be.dependency_analyzer.models.core import Node


IDE_BRIDGE_PROVIDERS = frozenset({"ide-bridge"})


def is_ide_bridge_provider(provider: str) -> bool:
    """Return True if *provider* uses task files for an external AI IDE."""
    return provider in IDE_BRIDGE_PROVIDERS


def is_api_keyless_provider(provider: str) -> bool:
    """Return True for providers that do not require a stored API key."""
    return is_ide_bridge_provider(provider)


class IDEBridgePendingTask(RuntimeError):
    """Raised when one or more IDE Bridge tasks need result files."""


class LLMBackend(abc.ABC):
    """Abstract LLM backend used by the documentation generator."""

    @abc.abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        """Single-shot text completion."""

    @abc.abstractmethod
    async def run_module_agent(
        self,
        module_name: str,
        components: Dict[str, "Node"],
        core_component_ids: List[str],
        module_path: List[str],
        working_dir: str,
    ) -> Dict[str, Any]:
        """Run the per-module agent loop.  Returns the updated module_tree dict."""

    async def plan_submodules(
        self,
        module_name: str,
        components: Dict[str, "Node"],
        core_component_ids: List[str],
        module_path: List[str],
        working_dir: str,
        module_tree: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        """Optionally plan child modules.

        Backends that do not support explicit planning return ``None`` so the
        original agent/tool workflow remains unchanged.
        """
        return None


def get_backend(config) -> "LLMBackend":
    """Return the backend instance matching ``config.provider``."""
    provider = getattr(config, "provider", "ide-bridge")
    if not is_ide_bridge_provider(provider):
        raise ValueError(
            f"Unsupported provider '{provider}'. This build supports only 'ide-bridge'."
        )
    from codewiki.src.be.ide_bridge_backend import IDEBridgeBackend
    return IDEBridgeBackend(config)

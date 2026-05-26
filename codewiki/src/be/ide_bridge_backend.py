"""IDE Bridge backend.

This backend lets CodeWiki run without a callable LLM API.  Whenever the
pipeline needs an LLM response, it writes a deterministic task file under the
docs output directory and stops.  The user can complete that task in an AI IDE
such as Windsurf, write the response to the matching result file, and rerun
``codewiki generate``.  Existing result files are consumed automatically, so the
pipeline is resumable.  Once the module tree exists, CodeWiki can batch all
currently-unblocked module tasks in one run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from codewiki.src.be.backend import IDEBridgePendingTask, LLMBackend
from codewiki.src.be.dependency_analyzer.models.core import Node
from codewiki.src.be.prompt_template import (
    format_leaf_system_prompt,
    format_user_prompt,
)
from codewiki.src.config import MODULE_TREE_FILENAME, OVERVIEW_FILENAME, Config
from codewiki.src.utils import file_manager


class IDEBridgeBackend(LLMBackend):
    """LLM backend that exchanges prompts and results via local files."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._bridge_dir = Path(config.docs_dir) / ".codewiki" / "ide_bridge"
        self._tasks_dir = self._bridge_dir / "tasks"
        self._results_dir = self._bridge_dir / "results"
        self.pending_tasks: list[dict[str, str]] = []

    def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        task_id = self._task_id("completion", prompt, model or "")
        result_path = self._results_dir / f"{task_id}.txt"
        if result_path.exists():
            return result_path.read_text(encoding="utf-8")

        task_path = self._tasks_dir / f"{task_id}.md"
        metadata = {
            "task_id": task_id,
            "kind": "completion",
            "model": model or self._config.main_model,
            "temperature": temperature,
            "result_path": str(result_path),
        }
        instructions = (
            "Complete this CodeWiki LLM task in your AI IDE.\n\n"
            f"Write the exact model response to:\n\n`{result_path}`\n\n"
            "Keep any requested XML-style wrapper tags from the prompt. For "
            "clustering tasks, the response must include the "
            "`<GROUPED_COMPONENTS>...</GROUPED_COMPONENTS>` block."
        )
        self._write_task(task_path, instructions, metadata, prompt)
        self._add_pending("completion", task_path, result_path)
        self.raise_if_pending()

    async def run_module_agent(
        self,
        module_name: str,
        components: Dict[str, Node],
        core_component_ids: List[str],
        module_path: List[str],
        working_dir: str,
    ) -> Dict[str, Any]:
        module_tree_path = os.path.join(working_dir, MODULE_TREE_FILENAME)
        module_tree = file_manager.load_json(module_tree_path)

        overview_docs_path = os.path.join(working_dir, OVERVIEW_FILENAME)
        if os.path.exists(overview_docs_path):
            return module_tree

        docs_path = os.path.join(working_dir, f"{module_name}.md")
        if os.path.exists(docs_path):
            return module_tree

        system_prompt = (
            "IDE Bridge mode note: you cannot call CodeWiki runtime tools in "
            "this environment. Use the code and module tree embedded in the "
            "user prompt, then produce the final markdown document directly.\n\n"
            + format_leaf_system_prompt(
            module_name,
            self._config.get_prompt_addition(),
            )
        )
        user_prompt = format_user_prompt(
            module_name=module_name,
            core_component_ids=core_component_ids,
            components=components,
            module_tree=module_tree,
        )
        prompt = f"<SYSTEM_PROMPT>\n{system_prompt}\n</SYSTEM_PROMPT>\n\n<USER_PROMPT>\n{user_prompt}\n</USER_PROMPT>"
        task_id = self._task_id("module", "/".join(module_path), prompt)
        result_path = self._results_dir / f"{task_id}.md"

        if result_path.exists():
            content = result_path.read_text(encoding="utf-8").strip()
            file_manager.save_text(content + "\n", docs_path)
            file_manager.save_json(module_tree, module_tree_path)
            return module_tree

        task_path = self._tasks_dir / f"{task_id}.md"
        metadata = {
            "task_id": task_id,
            "kind": "module_documentation",
            "module_name": module_name,
            "module_path": module_path,
            "core_component_ids": core_component_ids,
            "result_path": str(result_path),
            "docs_path": docs_path,
        }
        instructions = (
            "Generate the markdown documentation for this CodeWiki module in "
            "your AI IDE.\n\n"
            f"Write only the final markdown document to:\n\n`{result_path}`\n\n"
            "Do not include chat prefaces or code fences around the whole file. "
            "Mermaid diagrams inside the markdown are fine."
        )
        self._write_task(task_path, instructions, metadata, prompt)
        self._add_pending("module_documentation", task_path, result_path)
        return module_tree

    def _write_task(
        self,
        task_path: Path,
        instructions: str,
        metadata: Dict[str, Any],
        prompt: str,
    ) -> None:
        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        self._results_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = task_path.with_suffix(".json")

        if not task_path.exists():
            task_path.write_text(
                "# CodeWiki IDE Bridge Task\n\n"
                "## Instructions\n\n"
                f"{instructions}\n\n"
                "## Metadata\n\n"
                "```json\n"
                f"{json.dumps(metadata, indent=2)}\n"
                "```\n\n"
                "## Prompt\n\n"
                f"{prompt}\n",
                encoding="utf-8",
            )
        if not metadata_path.exists():
            metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def _add_pending(self, kind: str, task_path: Path, result_path: Path) -> None:
        task = {
            "kind": kind,
            "task_path": str(task_path),
            "result_path": str(result_path),
        }
        if task not in self.pending_tasks:
            self.pending_tasks.append(task)

    def has_pending_tasks(self) -> bool:
        return bool(self.pending_tasks)

    def raise_if_pending(self) -> None:
        if not self.pending_tasks:
            return

        lines = [
            f"IDE Bridge created {len(self.pending_tasks)} pending task(s).",
            "",
            "Complete them in your AI IDE, write each response to its result path,",
            "then rerun `codewiki generate`.",
            "",
        ]
        for index, task in enumerate(self.pending_tasks, 1):
            lines.extend(
                [
                    f"{index}. {task['kind']}",
                    f"   Task: {task['task_path']}",
                    f"   Result: {task['result_path']}",
                    "",
                ]
            )
        raise IDEBridgePendingTask("\n".join(lines).rstrip())

    @staticmethod
    def _task_id(kind: str, *parts: str) -> str:
        digest = hashlib.sha256("\n---\n".join(parts).encode("utf-8")).hexdigest()[:16]
        safe_kind = re.sub(r"[^a-zA-Z0-9_-]+", "_", kind).strip("_")
        return f"{safe_kind}_{digest}"

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

        task_fingerprint = json.dumps(
            {
                "module_name": module_name,
                "module_path": module_path,
                "core_component_ids": sorted(core_component_ids),
                "module_tree": module_tree,
            },
            sort_keys=True,
        )
        task_id = self._task_id("module", task_fingerprint)
        result_path = self._results_dir / f"{task_id}.md"
        task_body = self._format_module_task(
            module_name=module_name,
            components=components,
            core_component_ids=core_component_ids,
            module_path=module_path,
            working_dir=working_dir,
            module_tree=module_tree,
            result_path=result_path,
            docs_path=Path(docs_path),
        )

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
        self._write_task(task_path, task_body, metadata)
        self._add_pending("module_documentation", task_path, result_path)
        return module_tree

    def _format_module_task(
        self,
        *,
        module_name: str,
        components: Dict[str, Node],
        core_component_ids: List[str],
        module_path: List[str],
        working_dir: str,
        module_tree: Dict[str, Any],
        result_path: Path,
        docs_path: Path,
    ) -> str:
        """Create an AI-IDE-oriented task without embedding full source files."""
        source_files: dict[str, list[str]] = {}
        missing_components: list[str] = []
        repo_root = Path(self._config.repo_path).resolve()

        for component_id in core_component_ids:
            component = components.get(component_id)
            if component is None:
                missing_components.append(component_id)
                continue
            relative_path = self._component_relative_path(component, repo_root)
            source_files.setdefault(relative_path, []).append(component_id)

        source_lines: list[str] = []
        for index, (relative_path, ids) in enumerate(sorted(source_files.items()), 1):
            source_lines.append(f"{index}. `{relative_path}`")
            for component_id in sorted(ids):
                source_lines.append(f"   - `{component_id}`")

        custom_instructions = self._config.get_prompt_addition().strip()
        custom_section = ""
        if custom_instructions:
            custom_section = (
                "\n## Additional Instructions\n\n"
                f"{custom_instructions}\n"
            )

        missing_section = ""
        if missing_components:
            missing_section = (
                "\n## Components Not Found In Analysis Map\n\n"
                + "\n".join(f"- `{component_id}`" for component_id in missing_components)
                + "\n"
            )

        module_tree_path = Path(working_dir) / MODULE_TREE_FILENAME

        return (
            "# CodeWiki IDE Bridge Task\n\n"
            "You are working inside an AI IDE with access to the repository files. "
            "Do not treat this task file as the only source of truth; read the referenced "
            "source files directly from the workspace.\n\n"
            "## Goal\n\n"
            f"Generate architecture documentation for module `{module_name}`.\n\n"
            "## Output Contract\n\n"
            f"- Write only the final markdown document to `{result_path}`.\n"
            f"- CodeWiki will copy that result into `{docs_path}` on the next run.\n"
            "- Do not include chat prefaces, explanations about this task, or a code fence around the whole file.\n"
            "- Include Mermaid diagrams where they clarify architecture, dependencies, data flow, or user flow.\n"
            "- Link to related module docs when they exist instead of duplicating their content.\n"
            "- Keep the document useful to a developer maintaining this repository.\n\n"
            "## Repository Context\n\n"
            f"- Repository root: `{repo_root}`\n"
            f"- Documentation output directory: `{Path(working_dir).resolve()}`\n"
            f"- Module path: `{module_path or ['<repo>']}`\n"
            f"- Module tree file: `{module_tree_path}`\n"
            f"- Module tree currently has {len(module_tree)} top-level entries.\n\n"
            "## Source Files To Read\n\n"
            + ("\n".join(source_lines) if source_lines else "- No source files were provided by analysis.")
            + "\n"
            + custom_section
            + missing_section
            + "\n## Suggested Documentation Shape\n\n"
            "1. Purpose and scope\n"
            "2. High-level architecture\n"
            "3. Main components and responsibilities\n"
            "4. Important runtime flows\n"
            "5. Data model and persistence notes, if relevant\n"
            "6. Security/authentication notes, if relevant\n"
            "7. Extension and maintenance notes\n"
        )

    @staticmethod
    def _component_relative_path(component: Node, repo_root: Path) -> str:
        raw_path = Path(getattr(component, "file_path", "") or getattr(component, "relative_path", ""))
        if raw_path.is_absolute():
            try:
                return str(raw_path.resolve().relative_to(repo_root))
            except ValueError:
                return str(raw_path)
        return str(raw_path)

    def _write_task(
        self,
        task_path: Path,
        instructions: str,
        metadata: Dict[str, Any],
        prompt: str | None = None,
    ) -> None:
        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        self._results_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = task_path.with_suffix(".json")

        if not task_path.exists():
            body = instructions if instructions.lstrip().startswith("#") else (
                "# CodeWiki IDE Bridge Task\n\n"
                f"{instructions}"
            )
            task_path.write_text(
                f"{body.rstrip()}\n\n"
                + (f"\n## Prompt\n\n{prompt}\n" if prompt is not None else ""),
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

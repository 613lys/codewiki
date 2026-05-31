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
    SUBMODULE_PLANNING_PROMPT,
    format_leaf_system_prompt,
    format_system_prompt,
)
from codewiki.src.be.utils import is_complex_module
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
            "Complete this CodeWiki LLM task.\n\n"
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

    async def plan_submodules(
        self,
        module_name: str,
        components: Dict[str, Node],
        core_component_ids: List[str],
        module_path: List[str],
        working_dir: str,
        module_tree: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        core_component_references = self._format_component_references(
            components,
            core_component_ids,
        )
        prompt = SUBMODULE_PLANNING_PROMPT.format(
            module_name=module_name,
            module_tree=json.dumps(module_tree, indent=2),
            core_component_references=core_component_references,
        )
        task_id = self._task_id(
            "submodule_planning",
            module_name,
            "/".join(module_path),
            prompt,
        )
        result_path = self._results_dir / f"{task_id}.txt"
        if result_path.exists():
            return self._parse_submodule_result(result_path.read_text(encoding="utf-8"))

        task_path = self._tasks_dir / f"{task_id}.md"
        metadata = {
            "task_id": task_id,
            "kind": "submodule_planning",
            "module_name": module_name,
            "module_path": module_path,
            "core_component_ids": core_component_ids,
            "result_path": str(result_path),
        }
        instructions = (
            "Complete this CodeWiki planning task.\n\n"
            f"Write the exact response to:\n\n`{result_path}`\n\n"
            "The response must include exactly one "
            "`<SUB_MODULES>...</SUB_MODULES>` block."
        )
        self._write_task(task_path, instructions, metadata, prompt)
        self._add_pending("submodule_planning", task_path, result_path)
        self.raise_if_pending()
        return None

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
        repo_root = Path(self._config.repo_path).resolve()

        source_refs, missing_components = self._format_component_references_with_missing(
            components,
            core_component_ids,
            repo_root,
        )

        missing_section = ""
        if missing_components:
            missing_section = (
                "\n## Components Not Found In Analysis Map\n\n"
                + "\n".join(f"- `{component_id}`" for component_id in missing_components)
                + "\n"
            )

        formatted_module_tree = json.dumps(module_tree, indent=2)
        system_prompt = self._format_original_system_prompt(
            module_name=module_name,
            components=components,
            core_component_ids=core_component_ids,
        )
        user_prompt = self._format_ide_user_prompt(
            module_name=module_name,
            formatted_module_tree=formatted_module_tree,
            source_references=source_refs,
        )

        return (
            "# CodeWiki Task\n\n"
            "Complete the documentation task below.\n\n"
            "## Output Contract\n\n"
            f"- Write only the final markdown document to `{result_path}`.\n"
            "- Do not include chat prefaces, explanations about this task, or a code fence around the whole file.\n"
            f"- The final document will be copied to `{docs_path}` on the next run.\n\n"
            "## System Prompt\n\n"
            f"{system_prompt}\n"
            "\n## User Prompt\n\n"
            f"{user_prompt}\n"
            + missing_section
        )

    def _format_original_system_prompt(
        self,
        *,
        module_name: str,
        components: Dict[str, Node],
        core_component_ids: List[str],
    ) -> str:
        custom_instructions = self._config.get_prompt_addition()
        if is_complex_module(components, core_component_ids):
            return format_system_prompt(module_name, custom_instructions)
        return format_leaf_system_prompt(module_name, custom_instructions)

    def _format_component_references(
        self,
        components: Dict[str, Node],
        core_component_ids: List[str],
    ) -> str:
        refs, _ = self._format_component_references_with_missing(
            components,
            core_component_ids,
            Path(self._config.repo_path).resolve(),
        )
        return refs

    def _format_component_references_with_missing(
        self,
        components: Dict[str, Node],
        core_component_ids: List[str],
        repo_root: Path,
    ) -> tuple[str, list[str]]:
        source_files: dict[str, list[str]] = {}
        missing_components: list[str] = []
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

        if not source_lines:
            return "No source files were provided by analysis.", missing_components
        return "\n".join(source_lines), missing_components

    @staticmethod
    def _parse_submodule_result(response: str) -> Dict[str, Any]:
        import ast

        if "<SUB_MODULES>" not in response or "</SUB_MODULES>" not in response:
            raise ValueError("Submodule planning response missing <SUB_MODULES> block")
        content = response.split("<SUB_MODULES>", 1)[1].split("</SUB_MODULES>", 1)[0].strip()
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = ast.literal_eval(content)
        if not isinstance(parsed, dict):
            raise ValueError("Submodule planning response must be a dictionary")
        return parsed

    @staticmethod
    def _format_ide_user_prompt(
        *,
        module_name: str,
        formatted_module_tree: str,
        source_references: str,
    ) -> str:
        return (
            f"Generate comprehensive documentation for the {module_name} module "
            "using the provided module tree and core components.\n\n"
            "<MODULE_TREE>\n"
            f"{formatted_module_tree}\n"
            "</MODULE_TREE>\n"
            "* NOTE: You can refer the other modules in the module tree based on the "
            "dependencies between their core components to make the documentation more "
            "structured and avoid repeating the same information. Know that all "
            "documentation files are saved in the same folder not structured as module "
            "tree. e.g. [alt text]([ref_module_name].md)\n\n"
            "<CORE_COMPONENT_CODES>\n"
            "Read these source files from the repository workspace:\n\n"
            f"{source_references}\n"
            "</CORE_COMPONENT_CODES>"
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
                "# CodeWiki Task\n\n"
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

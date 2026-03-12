"""
Scoped knowledge/RAG loader for worker context injection.

Workers can have knowledge sources defined in their config YAML under
a `knowledge_sources` key. This module loads those files and formats them
for injection into the system prompt, giving workers domain-specific context.

Example config:
    knowledge_sources:
      - path: "configs/knowledge/domain_terms.yaml"
        inject_as: "reference"
      - path: "configs/knowledge/examples.yaml"
        inject_as: "few_shot"

Note: This module is implemented and ready for use. To wire it into a worker,
call load_knowledge_sources() with the worker config's knowledge_sources list
and prepend the result to the system prompt in LLMWorker.process().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml

logger = structlog.get_logger()


def load_knowledge_sources(sources: list[dict[str, Any]]) -> str:
    """
    Load knowledge sources and format them for system prompt injection.

    Each source has:
    - path: file path to the knowledge file
    - inject_as: "reference" (append to prompt) or "few_shot" (format as examples)
    """
    sections = []

    for source in sources:
        path = Path(source["path"])
        inject_as = source.get("inject_as", "reference")

        if not path.exists():
            logger.warning(
                "knowledge.source_not_found",
                path=str(path),
                inject_as=inject_as,
            )
            continue

        content = path.read_text()

        if inject_as == "reference":
            sections.append(f"\n--- Reference: {path.name} ---\n{content}")
        elif inject_as == "few_shot":
            sections.append(_format_few_shot(content, path.suffix))

    return "\n".join(sections)


def _format_few_shot(content: str, suffix: str) -> str:
    """Format content as few-shot examples."""
    if suffix in (".yaml", ".yml"):
        data = yaml.safe_load(content)
        if isinstance(data, list):
            examples = []
            for i, item in enumerate(data, 1):
                examples.append(f"\nExample {i}:")
                examples.append(f"Input: {item.get('input', '')}")
                examples.append(f"Output: {item.get('output', '')}")
            return "\n--- Few-Shot Examples ---" + "\n".join(examples)

    # For JSONL or plain text, return as-is with header
    return f"\n--- Few-Shot Examples ---\n{content}"

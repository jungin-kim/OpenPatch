from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from repooperator_worker.services.json_safe import json_safe


@dataclass
class SkillSpec:
    name: str
    description: str = ""
    when_to_use: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    prompt_template: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return json_safe(self)


@dataclass
class PluginSpec:
    name: str
    description: str = ""
    skills: list[SkillSpec] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    enabled_by_default: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return json_safe(self)


def skill_specs_from_discovered(discovered: list[dict[str, Any]]) -> list[SkillSpec]:
    specs: list[SkillSpec] = []
    for item in discovered:
        specs.append(
            SkillSpec(
                name=str(item.get("name") or ""),
                description=str(item.get("description") or ""),
                when_to_use=str(item.get("when_to_use") or item.get("description") or ""),
                allowed_tools=[str(tool) for tool in item.get("allowed_tools") or []],
                prompt_template=str(item.get("body") or ""),
                metadata=json_safe(
                    {
                        "identity": item.get("identity"),
                        "source_type": item.get("source_type"),
                        "source_path": item.get("source_path"),
                        "scope": item.get("scope"),
                        "enabled": item.get("enabled", True),
                    }
                ),
            )
        )
    return specs

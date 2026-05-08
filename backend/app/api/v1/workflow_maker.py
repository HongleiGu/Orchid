"""AI-assisted workflow/DAG drafting."""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.schemas import DataResponse
from app.api.v1.config import PipelineConfig
from app.config import get_settings
from app.models.client import model_client
from app.skills.registry import skill_registry

router = APIRouter(prefix="/workflow-maker", tags=["workflow-maker"])


class WorkflowDraftRequest(BaseModel):
    description: str = Field(..., min_length=1)
    name: str | None = None
    model: str | None = None


class SkillNeed(BaseModel):
    name: str
    reason: str = ""
    alternative: str | None = None


class WorkflowDraftResponse(BaseModel):
    plan: list[str] = []
    workflow: PipelineConfig
    required_skills: list[str] = []
    optional_skills: list[str] = []
    missing_required_skills: list[SkillNeed] = []
    missing_optional_skills: list[SkillNeed] = []
    notes: list[str] = []


@router.post("/draft", response_model=DataResponse[WorkflowDraftResponse])
async def draft_workflow(body: WorkflowDraftRequest):
    """Draft an import-ready DAG from a plain-language workflow request."""
    description = body.description.strip()
    if not description:
        raise HTTPException(400, "Workflow description is required")

    available_skills = sorted(skill_registry.all(), key=lambda skill: skill.name)
    available_skill_names = {skill.name for skill in available_skills}
    model = body.model or get_settings().llm_default_model

    system = _system_prompt(available_skills)
    user_message = _user_prompt(description, body.name)

    response = await model_client.complete(
        model=model,
        system=system,
        history=[],
        tools=[],
        user_message=user_message,
    )

    try:
        payload = _extract_json_object(response.content)
        draft = _normalise_draft(payload, available_skill_names)
    except ValueError as exc:
        raise HTTPException(502, f"Model did not return a usable workflow draft: {exc}") from exc

    return DataResponse(data=draft)


def _system_prompt(available_skills: list[Any]) -> str:
    skills_block = "\n".join(
        f"- {skill.name}: {skill.description}" for skill in available_skills
    ) or "- No skills are currently registered."

    return f"""You are Orchid's personal AI workflow/DAG maker.

Your job is to convert a user's workflow idea into an import-ready Orchid JSON config.

Think in four private passes before returning JSON:
1. Identify the necessary steps and decision logic.
2. Build a DAG skeleton with clear node names and edges.
3. Fill agent prompts, node inputs, task inputs, and input_schema.
4. Check which skills are available and report gaps.

Available Orchid skills:
{skills_block}

Return ONLY one JSON object with this exact top-level shape:
{{
  "plan": ["short implementation step", "..."],
  "workflow": {{
    "skills": [],
    "agents": [
      {{
        "name": "snake_case_agent_name",
        "role": "worker",
        "system_prompt": "precise operating instructions",
        "model": null,
        "skills": ["@orchid/available_skill_name"],
        "memory_strategy": "none",
        "reasoning": false
      }}
    ],
    "tasks": [
      {{
        "name": "Human readable task name",
        "description": "what this workflow does",
        "workflow_type": "dag",
        "workflow_config": {{
          "nodes": [
            {{"name": "node_name", "agent_name": "snake_case_agent_name"}}
          ],
          "edges": [
            {{"source": "node_a", "target": "node_b"}}
          ],
          "entry": "node_name"
        }},
        "inputs": {{}},
        "input_schema": [
          {{
            "name": "topic",
            "type": "string",
            "label": "Topic",
            "description": "what the user should provide",
            "required": true
          }}
        ],
        "cron_expr": null,
        "default_priority": 0
      }}
    ]
  }},
  "required_skills": ["@orchid/available_skill_name"],
  "optional_skills": [],
  "missing_required_skills": [
    {{"name": "missing skill name", "reason": "why it is needed", "alternative": "available fallback or null"}}
  ],
  "missing_optional_skills": [],
  "notes": ["short caveat or setup note"]
}}

Rules:
- Put only available skills in workflow.agents[].skills.
- Do not put bundled skill names in workflow.skills; keep workflow.skills as [] unless a marketplace package must be installed.
- If a needed skill is unavailable, do not include it in the workflow config. Report it in missing_required_skills or missing_optional_skills.
- Use workflow_type "dag" unless the user explicitly asks for a single-agent task.
- Every DAG node's agent_name must match one generated agent name.
- Every edge source/target must match a generated node name.
- Include conditional edges only when the condition can be expressed against output.content.
- Keep prompts practical: tell each agent what to read from task inputs and upstream DAG context.
- Prefer small reusable agents over many near-duplicate agents.
"""


def _user_prompt(description: str, name: str | None) -> str:
    label = f"\nPreferred workflow/task name: {name.strip()}" if name and name.strip() else ""
    return f"""Draft an Orchid workflow/DAG for this personal automation request:{label}

{description}
"""


def _extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if not text:
        raise ValueError("empty response")

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    elif not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("no JSON object found")
        text = text[start : end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from exc

    if not isinstance(data, dict):
        raise ValueError("top-level JSON value must be an object")
    return data


def _normalise_draft(data: dict[str, Any], available_skills: set[str]) -> WorkflowDraftResponse:
    workflow_data = data.get("workflow")
    if not isinstance(workflow_data, dict):
        raise ValueError("missing workflow object")

    missing_required = _skill_needs(data.get("missing_required_skills"))
    missing_optional = _skill_needs(data.get("missing_optional_skills"))
    missing_by_name = {need.name for need in missing_required + missing_optional}

    for agent in workflow_data.get("agents", []):
        if not isinstance(agent, dict):
            continue
        filtered: list[str] = []
        requested_skills = list(agent.get("tools") or []) + list(agent.get("skills") or [])
        for skill_name in requested_skills:
            if skill_name in available_skills:
                if skill_name not in filtered:
                    filtered.append(skill_name)
            elif skill_name not in missing_by_name:
                missing_required.append(SkillNeed(
                    name=str(skill_name),
                    reason="The draft agent requested this skill, but it is not registered in Orchid.",
                    alternative=None,
                ))
                missing_by_name.add(str(skill_name))
        agent["skills"] = filtered
        agent["tools"] = []

    for skill_name in workflow_data.get("skills") or []:
        if isinstance(skill_name, str) and skill_name not in missing_by_name:
            missing_required.append(SkillNeed(
                name=skill_name,
                reason="The draft requested this installable skill or package, but generated drafts do not auto-install dependencies.",
                alternative=None,
            ))
            missing_by_name.add(skill_name)
    workflow_data["skills"] = []

    workflow = PipelineConfig.model_validate(workflow_data)
    _validate_workflow_references(workflow)
    return WorkflowDraftResponse(
        plan=_string_list(data.get("plan")),
        workflow=workflow,
        required_skills=[s for s in _string_list(data.get("required_skills")) if s in available_skills],
        optional_skills=[s for s in _string_list(data.get("optional_skills")) if s in available_skills],
        missing_required_skills=missing_required,
        missing_optional_skills=missing_optional,
        notes=_string_list(data.get("notes")),
    )


def _validate_workflow_references(workflow: PipelineConfig) -> None:
    agent_names = {agent.name for agent in workflow.agents}
    for task in workflow.tasks:
        if task.workflow_type != "dag":
            continue

        cfg = task.workflow_config or {}
        nodes = cfg.get("nodes", [])
        if not isinstance(nodes, list) or not nodes:
            raise ValueError(f"Task '{task.name}' must include at least one DAG node")

        node_names: set[str] = set()
        for node in nodes:
            if not isinstance(node, dict):
                raise ValueError(f"Task '{task.name}' has an invalid DAG node")
            node_name = str(node.get("name") or "")
            agent_name = str(node.get("agent_name") or "")
            if not node_name:
                raise ValueError(f"Task '{task.name}' has a DAG node without a name")
            if agent_name not in agent_names:
                raise ValueError(f"Task '{task.name}' references unknown agent '{agent_name}'")
            node_names.add(node_name)

        entry = cfg.get("entry")
        if entry and entry not in node_names:
            raise ValueError(f"Task '{task.name}' references unknown entry node '{entry}'")

        for edge in cfg.get("edges", []):
            if not isinstance(edge, dict):
                raise ValueError(f"Task '{task.name}' has an invalid DAG edge")
            source = edge.get("source")
            target = edge.get("target")
            if source not in node_names or target not in node_names:
                raise ValueError(f"Task '{task.name}' has an edge with an unknown source or target")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _skill_needs(value: Any) -> list[SkillNeed]:
    if not isinstance(value, list):
        return []
    needs: list[SkillNeed] = []
    for item in value:
        if isinstance(item, str):
            needs.append(SkillNeed(name=item))
        elif isinstance(item, dict) and item.get("name"):
            needs.append(SkillNeed(
                name=str(item["name"]),
                reason=str(item.get("reason") or ""),
                alternative=(str(item["alternative"]) if item.get("alternative") is not None else None),
            ))
    return needs

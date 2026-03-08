#!/usr/bin/env python3
"""
Skill Tools — Browse and load reusable skill definitions.

Skills are stored as SKILL.md files under ~/.hermes-lite/skills/{name}/SKILL.md.
The prompt builder includes a compact index in the system prompt; these tools
let the agent load full skill content on demand and list what's available.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_HERMES_HOME = os.path.expanduser("~/.hermes-lite")


def _skills_dir() -> Path:
    home = Path(os.getenv("HERMES_HOME", DEFAULT_HERMES_HOME))
    return home / "skills"


def _read_frontmatter(path: Path) -> dict:
    """Extract YAML frontmatter fields from a SKILL.md file."""
    try:
        content = path.read_text(encoding="utf-8")
        match = re.match(r"^---\s*\n(.*?)^---\s*\n", content, re.MULTILINE | re.DOTALL)
        if not match:
            return {}
        fm = {}
        for line in match.group(1).splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                fm[key.strip()] = val.strip()
        return fm
    except Exception:
        return {}


# =============================================================================
# skills_list
# =============================================================================

def skills_list_tool(category: Optional[str] = None) -> str:
    """List available skills with descriptions."""
    sd = _skills_dir()
    if not sd.exists():
        return json.dumps({"skills": [], "message": "No skills directory found."})

    skills = []
    for skill_file in sorted(sd.rglob("SKILL.md")):
        name = skill_file.parent.name
        fm = _read_frontmatter(skill_file)
        desc = fm.get("description", "")
        # Truncate long descriptions for the listing
        if len(desc) > 120:
            desc = desc[:117] + "..."
        cat = skill_file.relative_to(sd).parts[0] if len(skill_file.relative_to(sd).parts) > 1 else "general"
        if category and cat != category:
            continue
        skills.append({"name": name, "category": cat, "description": desc})

    return json.dumps({"skills": skills, "count": len(skills)}, ensure_ascii=False)


SKILLS_LIST_SCHEMA = {
    "name": "skills_list",
    "description": (
        "List available skills. Skills are reusable expertise modules "
        "(e.g. frontend-design, webapp-testing) that provide detailed instructions "
        "for specific task types. Use this to discover what skills are available."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Optional category filter.",
            },
        },
        "required": [],
    },
}


# =============================================================================
# skill_view
# =============================================================================

def skill_view_tool(name: str) -> str:
    """Load a skill's full content by name."""
    if not name or not name.strip():
        return json.dumps({"error": "Skill name is required."})

    sd = _skills_dir()
    name = name.strip()

    # Try direct match first
    skill_path = sd / name / "SKILL.md"
    if not skill_path.exists():
        # Search recursively
        for candidate in sd.rglob("SKILL.md"):
            if candidate.parent.name == name:
                skill_path = candidate
                break

    if not skill_path.exists():
        available = [p.parent.name for p in sd.rglob("SKILL.md")]
        return json.dumps({
            "error": f"Skill '{name}' not found.",
            "available": available,
        })

    try:
        content = skill_path.read_text(encoding="utf-8")

        # Also load any reference files in the skill directory
        refs = {}
        for ref_file in skill_path.parent.rglob("*.md"):
            if ref_file.name != "SKILL.md":
                rel = str(ref_file.relative_to(skill_path.parent))
                ref_content = ref_file.read_text(encoding="utf-8")
                # Truncate very large reference files
                if len(ref_content) > 5000:
                    ref_content = ref_content[:5000] + "\n\n[Truncated]"
                refs[rel] = ref_content

        result = {"name": name, "content": content}
        if refs:
            result["references"] = refs
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to read skill: {e}"})


SKILL_VIEW_SCHEMA = {
    "name": "skill_view",
    "description": (
        "Load a skill's full instructions by name. Call this when you identify "
        "a skill that matches the current task (from the skills index in your "
        "system prompt). The skill content provides detailed instructions, "
        "patterns, and best practices to follow."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the skill to load (e.g. 'frontend-design').",
            },
        },
        "required": ["name"],
    },
}


# =============================================================================
# Checks
# =============================================================================

def check_skills_requirements() -> bool:
    return _skills_dir().exists()


# =============================================================================
# Registry
# =============================================================================

from tools.registry import registry

registry.register(
    name="skills_list",
    toolset="skills",
    schema=SKILLS_LIST_SCHEMA,
    handler=lambda args, **kw: skills_list_tool(category=args.get("category")),
    check_fn=check_skills_requirements,
)

registry.register(
    name="skill_view",
    toolset="skills",
    schema=SKILL_VIEW_SCHEMA,
    handler=lambda args, **kw: skill_view_tool(name=args.get("name", "")),
    check_fn=check_skills_requirements,
)

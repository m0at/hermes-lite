#!/usr/bin/env python3
"""
Delegate Tool — Agent-initiated task delegation in multi-agent swarm mode.

In TUI subprocess mode, emits a DelegateTask protocol message to the TUI,
which routes the task to the named target agent. The result is delivered
back asynchronously via CrossAgentContext.
"""

import json
import uuid

# =============================================================================
# Schema
# =============================================================================

DELEGATE_SCHEMA = {
    "name": "delegate_task",
    "description": (
        "Delegate a sub-task to another named agent in the swarm. "
        "The target agent will work on the task independently and the "
        "result will be delivered back to you as a system message when "
        "they finish.\n\n"
        "Use this when you want to:\n"
        "- Split work across multiple agents for parallel execution\n"
        "- Assign specialized tasks to agents with relevant expertise\n"
        "- Offload independent sub-tasks while you continue working\n\n"
        "You must know the target agent's name (set via /name in the TUI)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target_agent": {
                "type": "string",
                "description": "Name of the agent to delegate to (e.g. 'frontend', 'tester').",
            },
            "task": {
                "type": "string",
                "description": "Clear description of what the target agent should do.",
            },
            "context": {
                "type": "string",
                "description": "Optional context or background info for the task.",
            },
        },
        "required": ["target_agent", "task"],
    },
}


# =============================================================================
# Handler
# =============================================================================

def delegate_task(target_agent, task, context="", protocol=None):
    """Delegate a task to another agent via the subprocess protocol."""
    if not target_agent or not target_agent.strip():
        return json.dumps({"error": "target_agent is required."})
    if not task or not task.strip():
        return json.dumps({"error": "task is required."})

    if protocol is None:
        return json.dumps({
            "error": "delegate_task requires multi-agent TUI mode. "
                     "Not available in standalone CLI."
        })

    request_id = uuid.uuid4().hex[:8]
    protocol.emit_delegate_task(
        target_agent=target_agent.strip(),
        task=task.strip(),
        context=(context or "").strip(),
        request_id=request_id,
    )
    return json.dumps({
        "status": "delegated",
        "target_agent": target_agent.strip(),
        "request_id": request_id,
        "message": (
            f"Task delegated to @{target_agent.strip()}. "
            f"They will work on it independently. "
            f"The result will be delivered to you when they finish."
        ),
    })


def check_delegate_requirements():
    return True


# =============================================================================
# Registry
# =============================================================================

from tools.registry import registry

registry.register(
    name="delegate_task",
    toolset="delegate",
    schema=DELEGATE_SCHEMA,
    handler=lambda args, **kw: delegate_task(
        target_agent=args.get("target_agent", ""),
        task=args.get("task", ""),
        context=args.get("context", ""),
        protocol=kw.get("protocol")),
    check_fn=check_delegate_requirements,
)

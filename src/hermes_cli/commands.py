"""Slash command definitions and autocomplete for the Hermes CLI.

Contains the COMMANDS dict and the SlashCommandCompleter class.
These are pure data/UI with no HermesCLI state dependency.
"""

from prompt_toolkit.completion import Completer, Completion


COMMANDS = {
    "/help": "Show this help message",
    "/tools": "List available tools",
    "/toolsets": "List available toolsets",
    "/model": "Switch model (sonnet/haiku/qwen or full name)",
    "/prompt": "View/set custom system prompt",
    "/personality": "Set a predefined personality",
    "/clear": "Clear screen and reset conversation (fresh start)",
    "/history": "Show conversation history",
    "/new": "Start a new conversation (reset history)",
    "/reset": "Reset conversation only (keep screen)",
    "/retry": "Retry the last message (resend to agent)",
    "/undo": "Remove the last user/assistant exchange",
    "/save": "Save the current conversation",
    "/config": "Show current configuration",
    "/verbose": "Cycle tool progress display: off → new → all → verbose",
    "/thinkon": "Show model thinking/reasoning blocks in responses",
    "/thinkoff": "Hide model thinking/reasoning blocks from responses",
    "/compress": "Manually compress conversation context (flush memories + summarize)",
    "/usage": "Show token usage for the current session",
    "/context": "Show remaining context window (ASCII bar)",
    "/jobs": "List background agent tasks",
    "/fg": "Bring a background task to foreground (/fg <id>)",
    "/quit": "Exit the CLI (also: /exit, /q)",
}


class SlashCommandCompleter(Completer):
    """Autocomplete for /commands in the input area."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        word = text[1:]
        for cmd, desc in COMMANDS.items():
            cmd_name = cmd[1:]
            if cmd_name.startswith(word):
                yield Completion(
                    cmd_name,
                    start_position=-len(word),
                    display=cmd,
                    display_meta=desc,
                )

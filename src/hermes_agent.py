"""
HermesLiteAgent — subclass of AIAgent with memory, skills, and Honcho integration.

All hermes-lite-specific behavior lives here, keeping run_agent.py clean for
upstream sync with NousResearch/hermes-agent.
"""

import json
import logging
import time
import os
from datetime import datetime

from run_agent import AIAgent

logger = logging.getLogger(__name__)


class HermesLiteAgent(AIAgent):
    """AIAgent extended with persistent memory, skills, and Honcho."""

    _INLINE_TOOLS = AIAgent._INLINE_TOOLS | frozenset({"memory"})

    def __init__(self, *, skip_memory: bool = False, honcho_session_key: str = None, **kwargs):
        super().__init__(**kwargs)

        # ── Persistent memory (MEMORY.md) ──
        self._memory_store = None
        self._memory_enabled = False
        self._user_profile_enabled = False
        self._memory_nudge_interval = 10
        self._memory_flush_min_turns = 6
        if not skip_memory:
            try:
                from hermes_cli.config import load_config as _load_mem_config
                mem_config = _load_mem_config().get("memory", {})
                self._memory_enabled = mem_config.get("memory_enabled", False)
                self._user_profile_enabled = mem_config.get("user_profile_enabled", False)
                self._memory_nudge_interval = int(mem_config.get("nudge_interval", 10))
                self._memory_flush_min_turns = int(mem_config.get("flush_min_turns", 6))
                if self._memory_enabled or self._user_profile_enabled:
                    from tools.memory_tool import MemoryStore
                    self._memory_store = MemoryStore(
                        memory_char_limit=mem_config.get("memory_char_limit", 2200),
                        user_char_limit=mem_config.get("user_char_limit", 1375),
                    )
                    self._memory_store.load_from_disk()
            except Exception:
                pass

        # ── Honcho AI-native memory ──
        self._honcho = None
        self._honcho_session_key = honcho_session_key
        if not skip_memory:
            try:
                from honcho_integration.client import HonchoClientConfig, get_honcho_client
                hcfg = HonchoClientConfig.from_global_config()
                if hcfg.enabled and hcfg.api_key:
                    from honcho_integration.session import HonchoSessionManager
                    client = get_honcho_client(hcfg)
                    self._honcho = HonchoSessionManager(
                        honcho=client,
                        config=hcfg,
                        context_tokens=hcfg.context_tokens,
                    )
                    if not self._honcho_session_key:
                        self._honcho_session_key = (
                            hcfg.resolve_session_name() or "hermes-default"
                        )
                    self._honcho.get_or_create(self._honcho_session_key)
                    from tools.honcho_tools import set_session_context
                    set_session_context(self._honcho, self._honcho_session_key)
                    logger.info(
                        "Honcho active (session: %s, user: %s, workspace: %s)",
                        self._honcho_session_key, hcfg.peer_name, hcfg.workspace_id,
                    )
                else:
                    if not hcfg.enabled:
                        logger.debug("Honcho disabled in global config")
                    elif not hcfg.api_key:
                        logger.debug("Honcho enabled but no API key configured")
            except Exception as e:
                logger.debug("Honcho init failed (non-fatal): %s", e)
                self._honcho = None

        # ── Skills config ──
        self._skill_nudge_interval = 15
        try:
            from hermes_cli.config import load_config as _load_skills_config
            skills_config = _load_skills_config().get("skills", {})
            self._skill_nudge_interval = int(skills_config.get("creation_nudge_interval", 15))
        except Exception:
            pass

    # ── System prompt with memory + skills ──

    def _build_system_prompt(self, system_message: str = None) -> str:
        from agent.prompt_builder import (
            DEFAULT_AGENT_IDENTITY, PLATFORM_HINTS,
            MEMORY_GUIDANCE, SESSION_SEARCH_GUIDANCE, SKILLS_GUIDANCE,
            LOCAL_MODEL_TOOL_GUIDANCE,
            build_skills_system_prompt, build_context_files_prompt,
        )

        prompt_parts = [DEFAULT_AGENT_IDENTITY]

        if self.model.startswith("local/") and self.tools:
            prompt_parts.append(LOCAL_MODEL_TOOL_GUIDANCE)

        tool_guidance = []
        if "memory" in self.valid_tool_names:
            tool_guidance.append(MEMORY_GUIDANCE)
        if "session_search" in self.valid_tool_names:
            tool_guidance.append(SESSION_SEARCH_GUIDANCE)
        if "skill_manage" in self.valid_tool_names:
            tool_guidance.append(SKILLS_GUIDANCE)
        if tool_guidance:
            prompt_parts.append(" ".join(tool_guidance))

        if system_message is not None:
            prompt_parts.append(system_message)

        # Memory blocks
        if self._memory_store:
            if self._memory_enabled:
                mem_block = self._memory_store.format_for_system_prompt("memory")
                if mem_block:
                    prompt_parts.append(mem_block)
            if self._user_profile_enabled:
                user_block = self._memory_store.format_for_system_prompt("user")
                if user_block:
                    prompt_parts.append(user_block)

        # Skills index
        has_skills_tools = any(name in self.valid_tool_names for name in ['skills_list', 'skill_view', 'skill_manage'])
        skills_prompt = build_skills_system_prompt() if has_skills_tools else ""
        if skills_prompt:
            prompt_parts.append(skills_prompt)

        if not self.skip_context_files:
            context_files_prompt = build_context_files_prompt()
            if context_files_prompt:
                prompt_parts.append(context_files_prompt)

        now = datetime.now()
        prompt_parts.append(
            f"Conversation started: {now.strftime('%A, %B %d, %Y %I:%M %p')}"
        )

        platform_key = (self.platform or "").lower().strip()
        if platform_key in PLATFORM_HINTS:
            prompt_parts.append(PLATFORM_HINTS[platform_key])

        return "\n\n".join(prompt_parts)

    def _invalidate_system_prompt(self):
        self._cached_system_prompt = None
        if self._memory_store:
            self._memory_store.load_from_disk()

    # ── Context compression with memory flush + snapshot ──

    def _compress_context(self, messages: list, system_message: str, *, approx_tokens: int = None) -> tuple:
        # Pre-compression memory flush
        self.flush_memories(messages, min_turns=0)

        compressed = self.context_compressor.compress(messages, current_tokens=approx_tokens)

        todo_snapshot = self._todo_store.format_for_injection()
        if todo_snapshot:
            compressed.append({"role": "user", "content": todo_snapshot})

        if self._memory_store:
            mem_snapshot = self._memory_store.format_for_injection()
            if mem_snapshot:
                compressed.append({"role": "user", "content": mem_snapshot})

        self._invalidate_system_prompt()
        new_system_prompt = self._build_system_prompt(system_message)
        self._cached_system_prompt = new_system_prompt

        # Subprocess mode: notify TUI
        if self._subprocess_mode and self._protocol:
            old_tok = approx_tokens or 0
            new_tok = sum(len(str(m.get("content", ""))) for m in compressed) // 4
            self._protocol.emit_context_compressed(old_tok, new_tok)

        if self._session_db:
            try:
                import uuid
                self._session_db.end_session(self.session_id, "compression")
                old_session_id = self.session_id
                self.session_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
                self._session_db.create_session(
                    session_id=self.session_id,
                    source=self.platform or "cli",
                    model=self.model,
                    parent_session_id=old_session_id,
                )
                self._session_db.update_system_prompt(self.session_id, new_system_prompt)
            except Exception as e:
                logger.debug("Session DB compression split failed: %s", e)

        return compressed, new_system_prompt

    # ── Memory flush ──

    def flush_memories(self, messages: list = None, min_turns: int = None):
        """Give the model one turn to persist memories before context is lost."""
        if self._memory_flush_min_turns == 0 and min_turns is None:
            return
        if "memory" not in self.valid_tool_names or not self._memory_store:
            return
        effective_min = min_turns if min_turns is not None else self._memory_flush_min_turns
        if self._user_turn_count < effective_min:
            return

        if messages is None:
            messages = getattr(self, '_session_messages', None)
        if not messages or len(messages) < 3:
            return

        flush_content = (
            "[System: The session is being compressed. "
            "Please save anything worth remembering to your memories.]"
        )
        _sentinel = f"__flush_{id(self)}_{time.monotonic()}"
        flush_msg = {"role": "user", "content": flush_content, "_flush_sentinel": _sentinel}
        messages.append(flush_msg)

        try:
            api_messages = []
            for msg in messages:
                api_msg = msg.copy()
                if msg.get("role") == "assistant":
                    reasoning = msg.get("reasoning")
                    if reasoning:
                        api_msg["reasoning_content"] = reasoning
                api_msg.pop("reasoning", None)
                api_msg.pop("finish_reason", None)
                api_msg.pop("_flush_sentinel", None)
                api_messages.append(api_msg)

            if self._cached_system_prompt:
                api_messages = [{"role": "system", "content": self._cached_system_prompt}] + api_messages

            memory_tool_def = None
            for t in (self.tools or []):
                if t.get("function", {}).get("name") == "memory":
                    memory_tool_def = t
                    break

            if not memory_tool_def:
                messages.pop()
                return

            from agent.auxiliary_client import get_text_auxiliary_client
            aux_client, aux_model = get_text_auxiliary_client()

            if aux_client:
                api_kwargs = {
                    "model": aux_model,
                    "messages": api_messages,
                    "tools": [memory_tool_def],
                    "temperature": 0.3,
                    "max_tokens": 5120,
                }
                response = aux_client.chat.completions.create(**api_kwargs, timeout=30.0)
            elif self.api_mode == "codex_responses":
                codex_kwargs = self._build_api_kwargs(api_messages)
                codex_kwargs["tools"] = self._responses_tools([memory_tool_def])
                codex_kwargs["temperature"] = 0.3
                if "max_output_tokens" in codex_kwargs:
                    codex_kwargs["max_output_tokens"] = 5120
                response = self._run_codex_stream(codex_kwargs)
            else:
                api_kwargs = {
                    "model": self.model,
                    "messages": api_messages,
                    "tools": [memory_tool_def],
                    "temperature": 0.3,
                    **self._max_tokens_param(5120),
                }
                self._apply_qwen_params(api_kwargs)
                response = self._chat_completion(**api_kwargs, timeout=30.0, _skip_stream=True)

            tool_calls = []
            if self.api_mode == "codex_responses" and not aux_client:
                assistant_msg, _ = self._normalize_codex_response(response)
                if assistant_msg and assistant_msg.tool_calls:
                    tool_calls = assistant_msg.tool_calls
            elif hasattr(response, "choices") and response.choices:
                assistant_message = response.choices[0].message
                if assistant_message.tool_calls:
                    tool_calls = assistant_message.tool_calls

            for tc in tool_calls:
                if tc.function.name == "memory":
                    try:
                        args = json.loads(tc.function.arguments)
                        flush_target = args.get("target", "global")
                        from tools.memory_tool import memory_tool as _memory_tool
                        result = _memory_tool(
                            action=args.get("action"),
                            target=flush_target,
                            content=args.get("content"),
                            old_text=args.get("old_text"),
                            store=self._memory_store,
                        )
                        if self._honcho and flush_target == "user" and args.get("action") == "add":
                            self._honcho_save_user_observation(args.get("content", ""))
                        if not self.quiet_mode:
                            print(f"  ◆ Memory flush: saved to {args.get('target', 'global')}")
                    except Exception as e:
                        logger.debug("Memory flush tool call failed: %s", e)
        except Exception as e:
            logger.debug("Memory flush API call failed: %s", e)
        finally:
            while messages and messages[-1].get("_flush_sentinel") != _sentinel:
                messages.pop()
                if not messages:
                    break
            if messages and messages[-1].get("_flush_sentinel") == _sentinel:
                messages.pop()

    # ── Inline memory tool dispatch ──

    def _execute_single_tool(self, tool_call, display_idx: int, messages: list, effective_task_id: str) -> None:
        function_name = tool_call.function.name

        # Reset nudge counters
        if function_name == "memory":
            self._turns_since_memory = 0
        elif function_name == "skill_manage":
            self._iters_since_skill = 0

        if function_name == "memory":
            try:
                function_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                function_args = {}

            if not self.quiet_mode:
                args_str = json.dumps(function_args, ensure_ascii=False)
                args_preview = args_str[:self.log_prefix_chars] + "..." if len(args_str) > self.log_prefix_chars else args_str
                print(f"  › Tool {display_idx}: {function_name}({list(function_args.keys())}) - {args_preview}")

            if self._subprocess_mode and self._protocol:
                _sp_args_str = json.dumps(function_args, ensure_ascii=False)
                _sp_preview = _sp_args_str[:200] + "..." if len(_sp_args_str) > 200 else _sp_args_str
                self._protocol.emit_tool_call_start(
                    tool_id=getattr(tool_call, "id", "") or "",
                    tool_name=function_name,
                    args_preview=_sp_preview,
                )

            tool_start_time = time.time()
            target = function_args.get("target", "global")
            from tools.memory_tool import memory_tool as _memory_tool
            function_result = _memory_tool(
                action=function_args.get("action"),
                target=target,
                content=function_args.get("content"),
                old_text=function_args.get("old_text"),
                store=self._memory_store,
            )
            if self._honcho and target == "user" and function_args.get("action") == "add":
                self._honcho_save_user_observation(function_args.get("content", ""))
            tool_duration = time.time() - tool_start_time

            from agent.display import get_cute_tool_message as _get_cute_tool_message_impl
            if self.quiet_mode and self._show_display:
                print(f"  {_get_cute_tool_message_impl('memory', function_args, tool_duration, result=function_result)}")

            self._finalize_tool_result(tool_call, function_name, function_args, function_result, tool_duration, display_idx, messages)
        else:
            # Delegate to base class for all other tools
            super()._execute_single_tool(tool_call, display_idx, messages, effective_task_id)

    # ── Honcho helpers ──

    def _honcho_prefetch(self, user_message: str) -> str:
        if not self._honcho or not self._honcho_session_key:
            return ""
        try:
            ctx = self._honcho.get_prefetch_context(self._honcho_session_key, user_message)
            if not ctx:
                return ""
            parts = []
            rep = ctx.get("representation", "")
            card = ctx.get("card", "")
            if rep:
                parts.append(rep)
            if card:
                parts.append(card)
            if not parts:
                return ""
            return "# Honcho User Context\n" + "\n\n".join(parts)
        except Exception as e:
            logger.debug("Honcho prefetch failed (non-fatal): %s", e)
            return ""

    def _honcho_save_user_observation(self, content: str) -> str:
        if not content or not content.strip():
            return json.dumps({"success": False, "error": "Content cannot be empty."})
        try:
            session = self._honcho.get_or_create(self._honcho_session_key)
            session.add_message("user", f"[observation] {content.strip()}")
            self._honcho.save(session)
            return json.dumps({
                "success": True,
                "target": "user",
                "message": "Saved to Honcho user model.",
            })
        except Exception as e:
            logger.debug("Honcho user observation failed: %s", e)
            return json.dumps({"success": False, "error": f"Honcho save failed: {e}"})

    def _honcho_sync(self, user_content: str, assistant_content: str) -> None:
        if not self._honcho or not self._honcho_session_key:
            return
        try:
            session = self._honcho.get_or_create(self._honcho_session_key)
            session.add_message("user", user_content)
            session.add_message("assistant", assistant_content)
            self._honcho.save(session)
        except Exception as e:
            logger.debug("Honcho sync failed (non-fatal): %s", e)

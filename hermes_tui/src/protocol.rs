use serde::{Deserialize, Serialize};

// ── TUI → Agent ──────────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
#[serde(tag = "type")]
pub enum ToAgent {
    UserInput {
        session_id: String,
        message: String,
        model: String,
        max_iterations: u32,
    },
    ClarifyResponse {
        response: String,
    },
    /// Injected context from another agent's conversation (multi-agent mode).
    CrossAgentContext {
        from_agent: String,
        summary: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        full_history: Option<String>,
    },
    /// Sub-task delegated from another agent via the TUI.
    DelegatedTask {
        from_agent: String,
        request_id: String,
        task: String,
        context: String,
    },
    Interrupt,
    Shutdown,
}

// ── Agent → TUI ──────────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
#[serde(tag = "type")]
pub enum FromAgent {
    Token {
        content: String,
        #[serde(default)]
        is_thinking: bool,
    },
    ToolCallStart {
        tool_id: String,
        tool_name: String,
        #[serde(default)]
        args_preview: String,
    },
    ToolCallResult {
        tool_id: String,
        success: bool,
        output: String,
        #[serde(default)]
        duration_ms: u32,
    },
    ResponseComplete {
        finish_reason: String,
        #[serde(default)]
        input_tokens: u32,
        #[serde(default)]
        output_tokens: u32,
    },
    LoopStateChange {
        state: String,
        iteration: u32,
        action: String,
        #[serde(default)]
        message: String,
    },
    ClarifyRequest {
        question: String,
        #[serde(default)]
        choices: Vec<String>,
        #[serde(default = "default_timeout")]
        timeout_secs: u32,
    },
    ContextCompressed {
        old_tokens: u32,
        new_tokens: u32,
    },
    Done {
        reason: String,
        #[serde(default)]
        iterations: u32,
    },
    Error {
        message: String,
        #[serde(default)]
        code: String,
    },
    SessionInfo {
        session_id: String,
        model: String,
        #[serde(default)]
        context_length: u32,
    },
    Ready,

    // ── Skills ────────────────────────────────────────────────────────
    SkillStart {
        skill_name: String,
        #[serde(default)]
        display_name: String,
        #[serde(default)]
        scope: String, // "solo" or "multi"
        #[serde(default)]
        args: String,
    },
    SkillProgress {
        skill_name: String,
        step: String,
        #[serde(default)]
        step_number: u32,
        #[serde(default)]
        total_steps: u32,
        #[serde(default)]
        agent: String, // which agent reports (for multi-agent skills)
    },
    SkillComplete {
        skill_name: String,
        success: bool,
        #[serde(default)]
        summary: String,
        #[serde(default)]
        duration_ms: u32,
    },

    // ── Shared Memory ─────────────────────────────────────────────────
    MemoryOp {
        op: String, // "read", "write", "append", "list"
        file: String,
        #[serde(default)]
        preview: String,
    },

    // ── Multi-Agent ───────────────────────────────────────────────────
    /// Agent requests info from another agent.
    PeerQuery {
        target_agent: String,
        question: String,
        request_id: String,
    },
    /// Agent delegates a sub-task to another agent.
    DelegateTask {
        target_agent: String,
        task: String,
        #[serde(default)]
        context: String,
        request_id: String,
    },
    /// Result of a delegated task (routed back to requester).
    DelegationResult {
        request_id: String,
        result: String,
        success: bool,
    },
}

fn default_timeout() -> u32 {
    120
}

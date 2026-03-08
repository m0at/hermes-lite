mod session_db;

use pyo3::prelude::*;
use regex::Regex;
use std::sync::LazyLock;

pub use session_db::RustSessionDB;

// ── Regex patterns (compiled once) ─────────────────────────────────────

static RE_THINK_CLOSED: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?s)<think>.*?</think>").unwrap());
static RE_THINK_UNCLOSED: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?s)<think>.*").unwrap());
static RE_THINK_ORPHAN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?s)^.*?</think>\s*").unwrap());

static RE_TOOL_CALL_CLOSED: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?s)<tool_call>\s*.*?\s*</tool_call>").unwrap());
static RE_TOOL_CALL_UNCLOSED: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?s)<tool_call>.*").unwrap());

static RE_CONTEXT_THREATS: LazyLock<Vec<(Regex, &'static str)>> = LazyLock::new(|| {
    vec![
        (Regex::new(r"(?i)ignore\s+(previous|all|above|prior)\s+instructions").unwrap(), "prompt_injection"),
        (Regex::new(r"(?i)do\s+not\s+tell\s+the\s+user").unwrap(), "deception_hide"),
        (Regex::new(r"(?i)system\s+prompt\s+override").unwrap(), "sys_prompt_override"),
        (Regex::new(r"(?i)disregard\s+(your|all|any)\s+(instructions|rules|guidelines)").unwrap(), "disregard_rules"),
        (Regex::new(r"(?i)act\s+as\s+(if|though)\s+you\s+(have\s+no|don't\s+have)\s+(restrictions|limits|rules)").unwrap(), "bypass_restrictions"),
        (Regex::new(r"<!--[^>]*(?:ignore|override|system|secret|hidden)[^>]*-->").unwrap(), "html_comment_injection"),
        (Regex::new(r#"(?i)<\s*div\s+style\s*=\s*["'].*display\s*:\s*none"#).unwrap(), "hidden_div"),
        (Regex::new(r"(?i)translate\s+.*\s+into\s+.*\s+and\s+(execute|run|eval)").unwrap(), "translate_execute"),
        (Regex::new(r"(?i)curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)").unwrap(), "exfil_curl"),
        (Regex::new(r"(?i)cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass)").unwrap(), "read_secrets"),
    ]
});

static INVISIBLE_CHARS: &[char] = &[
    '\u{200b}', '\u{200c}', '\u{200d}', '\u{2060}', '\u{feff}',
    '\u{202a}', '\u{202b}', '\u{202c}', '\u{202d}', '\u{202e}',
];

// ── Enums ──────────────────────────────────────────────────────────────

#[pyclass(eq, eq_int)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LoopState {
    CheckInterrupt,
    PrepareRequest,
    ApiCall,
    ValidateResponse,
    ParseResponse,
    AdaptToolCalls,
    ValidateToolCalls,
    ExecuteTools,
    HandleFinalResponse,
    CheckScratchpad,
    HandleCodexIncomplete,
    Complete,
}

#[pyclass(eq, eq_int)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    Break,
    Retry,
    Nudge,
    Fail,
}

#[pyclass(eq, eq_int)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ResponseKind {
    Text,
    ToolCalls,
    Truncated,
    TruncatedToolCall,
    Invalid,
    EmptyAfterThink,
    IncompleteScratchpad,
    InvalidToolNames,
    InvalidToolJson,
    CodexIncomplete,
}

// ── Transition ─────────────────────────────────────────────────────────

#[pyclass]
#[derive(Clone, Debug)]
pub struct Transition {
    #[pyo3(get)]
    pub state: LoopState,
    #[pyo3(get)]
    pub action: Action,
    #[pyo3(get)]
    pub message: String,
}

impl Transition {
    fn new(state: LoopState, action: Action, message: impl Into<String>) -> Self {
        Self { state, action, message: message.into() }
    }

    fn advance(state: LoopState) -> Self {
        Self::new(state, Action::Break, "")
    }
}

// ── AgentLoopMachine ───────────────────────────────────────────────────

#[pyclass]
pub struct AgentLoopMachine {
    state: LoopState,
    max_iterations: u32,
    needs_tool_adapter: bool,
    _is_codex: bool,
    max_api_retries: u32,
    iteration: u32,
    interrupted: bool,
    completed: bool,

    // Retry counters
    api_retries: u32,
    truncated_tc_retries: u32,
    invalid_tool_retries: u32,
    invalid_json_retries: u32,
    incomplete_scratchpad_retries: u32,
    empty_after_think_retries: u32,
    codex_incomplete_retries: u32,
}

#[pymethods]
impl AgentLoopMachine {
    #[new]
    #[pyo3(signature = (max_iterations, needs_tool_adapter=false, is_codex=false, max_api_retries=6))]
    fn new(
        max_iterations: u32,
        needs_tool_adapter: bool,
        is_codex: bool,
        max_api_retries: u32,
    ) -> Self {
        Self {
            state: LoopState::CheckInterrupt,
            max_iterations,
            needs_tool_adapter,
            _is_codex: is_codex,
            max_api_retries,
            iteration: 0,
            interrupted: false,
            completed: false,
            api_retries: 0,
            truncated_tc_retries: 0,
            invalid_tool_retries: 0,
            invalid_json_retries: 0,
            incomplete_scratchpad_retries: 0,
            empty_after_think_retries: 0,
            codex_incomplete_retries: 0,
        }
    }

    #[getter]
    fn state(&self) -> LoopState {
        self.state
    }

    #[getter]
    fn iteration(&self) -> u32 {
        self.iteration
    }

    #[getter]
    fn interrupted(&self) -> bool {
        self.interrupted
    }

    #[getter]
    fn completed(&self) -> bool {
        self.completed
    }

    fn begin_iteration(&mut self) -> Option<Transition> {
        self.iteration += 1;
        self.api_retries = 0;
        self.state = LoopState::CheckInterrupt;

        if self.iteration > self.max_iterations {
            self.completed = true;
            self.state = LoopState::Complete;
            Some(Transition::new(
                LoopState::Complete,
                Action::Break,
                format!("Max iterations ({}) exceeded", self.max_iterations),
            ))
        } else {
            None
        }
    }

    fn step(&mut self, response_kind: ResponseKind) -> Transition {
        match self.state {
            LoopState::CheckInterrupt => {
                if self.interrupted {
                    self.completed = true;
                    self.state = LoopState::Complete;
                    Transition::new(LoopState::Complete, Action::Break, "Interrupted")
                } else {
                    self.state = LoopState::PrepareRequest;
                    Transition::advance(LoopState::PrepareRequest)
                }
            }

            LoopState::PrepareRequest => {
                self.state = LoopState::ApiCall;
                Transition::advance(LoopState::ApiCall)
            }

            LoopState::ApiCall => match response_kind {
                ResponseKind::Invalid => {
                    self.api_retries += 1;
                    if self.api_retries >= self.max_api_retries {
                        self.state = LoopState::Complete;
                        Transition::new(
                            LoopState::Complete,
                            Action::Fail,
                            format!("API retries exhausted ({}/{})", self.api_retries, self.max_api_retries),
                        )
                    } else {
                        // Stay in ApiCall for retry
                        Transition::new(
                            LoopState::ApiCall,
                            Action::Retry,
                            format!("{}/{}", self.api_retries, self.max_api_retries),
                        )
                    }
                }
                _ => {
                    self.api_retries = 0;
                    self.state = LoopState::ValidateResponse;
                    Transition::advance(LoopState::ValidateResponse)
                }
            },

            LoopState::ValidateResponse => match response_kind {
                ResponseKind::Truncated => {
                    self.state = LoopState::Complete;
                    Transition::new(LoopState::Complete, Action::Fail, "Response truncated (length)")
                }
                _ => {
                    self.state = LoopState::ParseResponse;
                    Transition::advance(LoopState::ParseResponse)
                }
            },

            LoopState::ParseResponse => match response_kind {
                ResponseKind::IncompleteScratchpad => {
                    self.state = LoopState::CheckScratchpad;
                    Transition::advance(LoopState::CheckScratchpad)
                }
                _ => {
                    if self.needs_tool_adapter {
                        self.state = LoopState::AdaptToolCalls;
                        Transition::advance(LoopState::AdaptToolCalls)
                    } else {
                        self.state = LoopState::ValidateToolCalls;
                        Transition::advance(LoopState::ValidateToolCalls)
                    }
                }
            },

            LoopState::CheckScratchpad => {
                self.incomplete_scratchpad_retries += 1;
                if self.incomplete_scratchpad_retries <= 2 {
                    self.state = LoopState::CheckInterrupt;
                    Transition::new(
                        LoopState::CheckInterrupt,
                        Action::Retry,
                        format!("{}/2", self.incomplete_scratchpad_retries),
                    )
                } else {
                    self.state = LoopState::Complete;
                    Transition::new(
                        LoopState::Complete,
                        Action::Fail,
                        "Incomplete scratchpad after 2 retries",
                    )
                }
            }

            LoopState::AdaptToolCalls => match response_kind {
                ResponseKind::TruncatedToolCall => {
                    self.truncated_tc_retries += 1;
                    if self.truncated_tc_retries < 3 {
                        self.state = LoopState::PrepareRequest;
                        Transition::new(
                            LoopState::PrepareRequest,
                            Action::Nudge,
                            format!("{}/3", self.truncated_tc_retries),
                        )
                    } else {
                        // After 3 truncations, treat as text (strip tags, show as final response)
                        self.truncated_tc_retries = 0;
                        self.state = LoopState::HandleFinalResponse;
                        Transition::advance(LoopState::HandleFinalResponse)
                    }
                }
                ResponseKind::ToolCalls => {
                    self.truncated_tc_retries = 0;
                    self.state = LoopState::ValidateToolCalls;
                    Transition::advance(LoopState::ValidateToolCalls)
                }
                _ => {
                    // No tool calls found by adapter → final response
                    self.state = LoopState::HandleFinalResponse;
                    Transition::advance(LoopState::HandleFinalResponse)
                }
            },

            LoopState::ValidateToolCalls => match response_kind {
                ResponseKind::ToolCalls => {
                    self.invalid_tool_retries = 0;
                    self.invalid_json_retries = 0;
                    self.state = LoopState::ExecuteTools;
                    Transition::advance(LoopState::ExecuteTools)
                }
                ResponseKind::InvalidToolNames => {
                    self.invalid_tool_retries += 1;
                    if self.invalid_tool_retries < 3 {
                        self.state = LoopState::CheckInterrupt;
                        Transition::new(
                            LoopState::CheckInterrupt,
                            Action::Retry,
                            format!("{}/3", self.invalid_tool_retries),
                        )
                    } else {
                        self.invalid_tool_retries = 0;
                        self.state = LoopState::Complete;
                        Transition::new(LoopState::Complete, Action::Fail, "Invalid tool names after 3 retries")
                    }
                }
                ResponseKind::InvalidToolJson => {
                    self.invalid_json_retries += 1;
                    if self.invalid_json_retries < 3 {
                        self.state = LoopState::CheckInterrupt;
                        Transition::new(
                            LoopState::CheckInterrupt,
                            Action::Retry,
                            format!("{}/3", self.invalid_json_retries),
                        )
                    } else {
                        self.invalid_json_retries = 0;
                        self.state = LoopState::PrepareRequest;
                        Transition::new(
                            LoopState::PrepareRequest,
                            Action::Nudge,
                            "Invalid JSON after 3 retries — injecting recovery",
                        )
                    }
                }
                _ => {
                    // No tool calls → final response
                    self.state = LoopState::HandleFinalResponse;
                    Transition::advance(LoopState::HandleFinalResponse)
                }
            },

            LoopState::ExecuteTools => {
                // After executing tools, loop back for next iteration
                self.state = LoopState::CheckInterrupt;
                Transition::advance(LoopState::CheckInterrupt)
            }

            LoopState::HandleFinalResponse => match response_kind {
                ResponseKind::EmptyAfterThink => {
                    self.empty_after_think_retries += 1;
                    if self.empty_after_think_retries <= 3 {
                        self.state = LoopState::PrepareRequest;
                        Transition::new(
                            LoopState::PrepareRequest,
                            Action::Nudge,
                            format!("{}/3", self.empty_after_think_retries),
                        )
                    } else {
                        self.empty_after_think_retries = 0;
                        self.state = LoopState::Complete;
                        Transition::new(LoopState::Complete, Action::Fail, "Empty after think, 3 retries exhausted")
                    }
                }
                ResponseKind::CodexIncomplete => {
                    self.codex_incomplete_retries += 1;
                    if self.codex_incomplete_retries <= 3 {
                        self.state = LoopState::CheckInterrupt;
                        Transition::new(
                            LoopState::CheckInterrupt,
                            Action::Retry,
                            format!("{}/3", self.codex_incomplete_retries),
                        )
                    } else {
                        self.codex_incomplete_retries = 0;
                        self.state = LoopState::Complete;
                        Transition::new(LoopState::Complete, Action::Fail, "Codex incomplete after 3 retries")
                    }
                }
                _ => {
                    self.completed = true;
                    self.state = LoopState::Complete;
                    Transition::new(LoopState::Complete, Action::Break, "")
                }
            },

            LoopState::HandleCodexIncomplete => {
                self.codex_incomplete_retries += 1;
                if self.codex_incomplete_retries <= 3 {
                    self.state = LoopState::CheckInterrupt;
                    Transition::new(
                        LoopState::CheckInterrupt,
                        Action::Retry,
                        format!("{}/3", self.codex_incomplete_retries),
                    )
                } else {
                    self.codex_incomplete_retries = 0;
                    self.state = LoopState::Complete;
                    Transition::new(LoopState::Complete, Action::Fail, "Codex incomplete after 3 retries")
                }
            }

            LoopState::Complete => {
                Transition::new(LoopState::Complete, Action::Break, "Already complete")
            }
        }
    }

    fn set_interrupted(&mut self) {
        self.interrupted = true;
    }

    fn reset(&mut self) {
        self.state = LoopState::CheckInterrupt;
        self.iteration = 0;
        self.interrupted = false;
        self.completed = false;
        self.api_retries = 0;
        self.truncated_tc_retries = 0;
        self.invalid_tool_retries = 0;
        self.invalid_json_retries = 0;
        self.incomplete_scratchpad_retries = 0;
        self.empty_after_think_retries = 0;
        self.codex_incomplete_retries = 0;
    }

    fn debug_counters(&self) -> std::collections::HashMap<String, u32> {
        let mut m = std::collections::HashMap::new();
        m.insert("iteration".into(), self.iteration);
        m.insert("api_retries".into(), self.api_retries);
        m.insert("truncated_tc_retries".into(), self.truncated_tc_retries);
        m.insert("invalid_tool_retries".into(), self.invalid_tool_retries);
        m.insert("invalid_json_retries".into(), self.invalid_json_retries);
        m.insert("incomplete_scratchpad_retries".into(), self.incomplete_scratchpad_retries);
        m.insert("empty_after_think_retries".into(), self.empty_after_think_retries);
        m.insert("codex_incomplete_retries".into(), self.codex_incomplete_retries);
        m
    }

    #[staticmethod]
    #[pyo3(signature = (content, has_tool_calls, finish_reason, is_codex, has_tag_start, has_tag_close, has_incomplete_scratchpad, tool_names_valid, tool_json_valid))]
    #[allow(unused_variables)]
    fn classify_content(
        content: &str,
        has_tool_calls: bool,
        finish_reason: &str,
        is_codex: bool,
        has_tag_start: bool,
        has_tag_close: bool,
        has_incomplete_scratchpad: bool,
        tool_names_valid: bool,
        tool_json_valid: bool,
    ) -> ResponseKind {
        // Priority order matters — check most specific conditions first

        // Truncated output
        if finish_reason == "length" {
            return ResponseKind::Truncated;
        }

        // Incomplete scratchpad
        if has_incomplete_scratchpad {
            return ResponseKind::IncompleteScratchpad;
        }

        // Codex incomplete
        if is_codex && finish_reason == "incomplete" {
            return ResponseKind::CodexIncomplete;
        }

        // Has structured tool calls from API
        if has_tool_calls {
            if !tool_names_valid {
                return ResponseKind::InvalidToolNames;
            }
            if !tool_json_valid {
                return ResponseKind::InvalidToolJson;
            }
            return ResponseKind::ToolCalls;
        }

        // Has tool_call XML tag but no structured tool calls (truncated or parse failed)
        if has_tag_start {
            return ResponseKind::TruncatedToolCall;
        }

        // Empty after think blocks
        if !content.is_empty() && !has_content_after_think_inner(content) {
            return ResponseKind::EmptyAfterThink;
        }

        ResponseKind::Text
    }

    fn __repr__(&self) -> String {
        format!(
            "AgentLoopMachine(state={:?}, iter={}, interrupted={}, completed={})",
            self.state, self.iteration, self.interrupted, self.completed
        )
    }
}

// ── Utility functions ──────────────────────────────────────────────────

fn strip_think_blocks_inner(content: &str) -> String {
    if content.is_empty() {
        return String::new();
    }
    // 1. Remove closed <think>...</think> blocks
    let result = RE_THINK_CLOSED.replace_all(content, "");
    // 2. Remove unclosed <think>... (to end of string)
    let result = RE_THINK_UNCLOSED.replace_all(&result, "");
    // 3. Remove orphaned </think> with preceding content
    let result = RE_THINK_ORPHAN.replace_all(&result, "");
    result.into_owned()
}

fn has_content_after_think_inner(content: &str) -> bool {
    if content.is_empty() {
        return false;
    }
    let cleaned = RE_THINK_CLOSED.replace_all(content, "");
    !cleaned.trim().is_empty()
}

fn strip_tool_call_blocks_inner(content: &str) -> String {
    if content.is_empty() {
        return String::new();
    }
    // Remove closed <tool_call>...</tool_call> blocks
    let result = RE_TOOL_CALL_CLOSED.replace_all(content, "");
    // Remove unclosed/truncated <tool_call>... (to end)
    let result = RE_TOOL_CALL_UNCLOSED.replace_all(&result, "");
    result.into_owned()
}

fn scan_context_content_inner(content: &str, filename: &str) -> String {
    let mut findings = Vec::new();

    // Check invisible unicode characters
    for &ch in INVISIBLE_CHARS {
        if content.contains(ch) {
            findings.push(format!("invisible unicode U+{:04X}", ch as u32));
        }
    }

    // Check threat patterns
    for (re, pid) in RE_CONTEXT_THREATS.iter() {
        if re.is_match(content) {
            findings.push(pid.to_string());
        }
    }

    if findings.is_empty() {
        content.to_string()
    } else {
        format!(
            "[BLOCKED: {} contained potential prompt injection ({}). Content not loaded.]",
            filename,
            findings.join(", ")
        )
    }
}

// ── PyO3 module ────────────────────────────────────────────────────────

#[pyfunction]
fn strip_think_blocks(content: &str) -> String {
    strip_think_blocks_inner(content)
}

#[pyfunction]
fn has_content_after_think(content: &str) -> bool {
    has_content_after_think_inner(content)
}

#[pyfunction]
fn strip_tool_call_blocks(content: &str) -> String {
    strip_tool_call_blocks_inner(content)
}

#[pyfunction]
fn scan_context_content(content: &str, filename: &str) -> String {
    scan_context_content_inner(content, filename)
}

#[pymodule]
fn hermes_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<LoopState>()?;
    m.add_class::<Action>()?;
    m.add_class::<ResponseKind>()?;
    m.add_class::<Transition>()?;
    m.add_class::<AgentLoopMachine>()?;
    m.add_function(wrap_pyfunction!(strip_think_blocks, m)?)?;
    m.add_function(wrap_pyfunction!(has_content_after_think, m)?)?;
    m.add_function(wrap_pyfunction!(strip_tool_call_blocks, m)?)?;
    m.add_function(wrap_pyfunction!(scan_context_content, m)?)?;
    m.add_class::<RustSessionDB>()?;
    Ok(())
}

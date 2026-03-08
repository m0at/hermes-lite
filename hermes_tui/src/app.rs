use std::time::Instant;

use ratatui::prelude::Direction;

// ── Message types for conversation history ───────────────────────────────

#[derive(Debug, Clone)]
pub enum MessagePart {
    Text(String),
    ThinkBlock(String),
    ToolCall {
        tool_id: String,
        tool_name: String,
        args_preview: String,
        status: ToolStatus,
    },
}

#[derive(Debug, Clone)]
pub enum ToolStatus {
    Running(Instant),
    Done {
        success: bool,
        output: String,
        duration_ms: u32,
    },
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Role {
    User,
    Assistant,
    System,
}

#[derive(Debug, Clone)]
pub struct Message {
    pub role: Role,
    pub parts: Vec<MessagePart>,
}

// ── Active pane ──────────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ActivePane {
    Input,
    History,
}

// ── Slash commands ───────────────────────────────────────────────────────

pub enum SlashCommand {
    Help,
    Clear,
    New,
    Model(String),
    Verbose,
    ThinkOn,
    ThinkOff,
    Compress,
    Usage,
    Context,
    Save,
    Config,
    Tools,
    Jobs,
    Quit,
    Unknown(String),
    // Multi-agent commands
    Split,
    HSplit,
    Tabs,
    Close,
    Name(String),
    Focus(String),
    Broadcast(String),
    Ask { target: String, message: String },
    ListAgents,
    Zoom,
    Skills,
}

impl SlashCommand {
    pub fn parse(input: &str) -> Option<Self> {
        let trimmed = input.trim();
        if !trimmed.starts_with('/') {
            return None;
        }
        let mut parts = trimmed[1..].splitn(2, ' ');
        let cmd = parts.next().unwrap_or("");
        let arg = parts.next().unwrap_or("").to_string();

        Some(match cmd {
            "help" => Self::Help,
            "clear" => Self::Clear,
            "new" | "reset" => Self::New,
            "model" => Self::Model(arg),
            "verbose" => Self::Verbose,
            "thinkon" => Self::ThinkOn,
            "thinkoff" => Self::ThinkOff,
            "compress" => Self::Compress,
            "usage" => Self::Usage,
            "context" => Self::Context,
            "save" => Self::Save,
            "config" => Self::Config,
            "tools" | "toolsets" => Self::Tools,
            "jobs" => Self::Jobs,
            "quit" | "exit" | "q" => Self::Quit,
            // Multi-agent commands
            "split" | "vsplit" => Self::Split,
            "hsplit" => Self::HSplit,
            "tabs" => Self::Tabs,
            "close" => Self::Close,
            "name" => Self::Name(arg),
            "focus" => Self::Focus(arg),
            "broadcast" => Self::Broadcast(arg),
            "ask" => {
                // /ask <target> <message>
                let mut ask_parts = arg.splitn(2, ' ');
                let target = ask_parts.next().unwrap_or("").to_string();
                let message = ask_parts.next().unwrap_or("").to_string();
                if target.is_empty() {
                    Self::Unknown("ask (missing target)".to_string())
                } else {
                    Self::Ask { target, message }
                }
            }
            "agents" | "list-agents" => Self::ListAgents,
            "zoom" => Self::Zoom,
            "skills" => Self::Skills,
            other => Self::Unknown(other.to_string()),
        })
    }

    pub fn completions(prefix: &str) -> Vec<(&'static str, &'static str)> {
        const COMMANDS: &[(&str, &str)] = &[
            ("/help", "Show this help message"),
            ("/tools", "List available tools"),
            ("/model", "Switch model"),
            ("/clear", "Clear screen and reset conversation"),
            ("/new", "Start a new conversation"),
            ("/verbose", "Cycle tool progress display"),
            ("/thinkon", "Show model thinking blocks"),
            ("/thinkoff", "Hide model thinking blocks"),
            ("/compress", "Manually compress context"),
            ("/usage", "Show token usage"),
            ("/context", "Show remaining context window"),
            ("/save", "Save conversation"),
            ("/config", "Show current configuration"),
            ("/jobs", "List background tasks"),
            ("/quit", "Exit the CLI"),
            // Multi-agent commands
            ("/split", "Spawn new agent in vertical split"),
            ("/hsplit", "Spawn new agent in horizontal split"),
            ("/tabs", "Switch to tab layout mode"),
            ("/close", "Close focused agent pane"),
            ("/name", "Rename focused agent"),
            ("/focus", "Focus agent by name or index"),
            ("/broadcast", "Send message to all agents"),
            ("/ask", "Send message to named agent, pull response back"),
            ("/agents", "List all agents and their status"),
            ("/zoom", "Toggle zoom on focused pane"),
            ("/skills", "List available skills"),
        ];

        let word = if prefix.starts_with('/') {
            &prefix[1..]
        } else {
            prefix
        };

        COMMANDS
            .iter()
            .filter(|(cmd, _)| cmd[1..].starts_with(word))
            .copied()
            .collect()
    }
}

// ── Per-agent pane state ─────────────────────────────────────────────────

pub struct AgentPane {
    pub id: u8,
    pub name: String,

    // Conversation
    pub messages: Vec<Message>,
    pub scroll_offset: u16,
    pub history_height: u16,

    // Session
    pub session_id: String,
    pub model: String,

    // Tokens
    pub input_tokens: u32,
    pub output_tokens: u32,
    pub context_length: u32,

    // Agent state
    pub agent_running: bool,
    pub loop_state: String,
    pub loop_iteration: u32,
    pub streaming_text: String,
    pub is_thinking: bool,

    // Spinner (per-agent since each can be independently busy)
    pub spinner_frame: usize,
    pub last_spinner_tick: Instant,

    // Status
    pub status_message: Option<(String, Instant)>,

    // Has unread output since last focus
    pub unread: bool,
}

impl AgentPane {
    pub fn new(id: u8) -> Self {
        Self {
            id,
            name: format!("a{}", id + 1),
            messages: Vec::new(),
            scroll_offset: 0,
            history_height: 0,
            session_id: String::new(),
            model: String::new(),
            input_tokens: 0,
            output_tokens: 0,
            context_length: 200_000,
            agent_running: false,
            loop_state: String::new(),
            loop_iteration: 0,
            streaming_text: String::new(),
            is_thinking: false,
            spinner_frame: 0,
            last_spinner_tick: Instant::now(),
            status_message: None,
            unread: false,
        }
    }

    pub fn add_user_message(&mut self, text: String) {
        self.messages.push(Message {
            role: Role::User,
            parts: vec![MessagePart::Text(text)],
        });
        self.scroll_to_bottom();
    }

    pub fn begin_assistant_message(&mut self) {
        self.messages.push(Message {
            role: Role::Assistant,
            parts: Vec::new(),
        });
        self.streaming_text.clear();
        self.is_thinking = false;
    }

    pub fn append_token(&mut self, content: &str, is_thinking: bool) {
        if is_thinking != self.is_thinking {
            self.flush_streaming_part();
            self.is_thinking = is_thinking;
        }
        self.streaming_text.push_str(content);
        self.scroll_to_bottom();
    }

    pub fn flush_streaming_part(&mut self) {
        if self.streaming_text.is_empty() {
            return;
        }
        let text = std::mem::take(&mut self.streaming_text);
        let part = if self.is_thinking {
            MessagePart::ThinkBlock(text)
        } else {
            MessagePart::Text(text)
        };
        if let Some(msg) = self.messages.last_mut() {
            msg.parts.push(part);
        }
    }

    pub fn add_tool_call(&mut self, tool_id: String, tool_name: String, args_preview: String) {
        self.flush_streaming_part();
        if let Some(msg) = self.messages.last_mut() {
            msg.parts.push(MessagePart::ToolCall {
                tool_id,
                tool_name,
                args_preview,
                status: ToolStatus::Running(Instant::now()),
            });
        }
    }

    pub fn complete_tool_call(
        &mut self,
        tool_id: &str,
        success: bool,
        output: String,
        duration_ms: u32,
    ) {
        if let Some(msg) = self.messages.last_mut() {
            for part in &mut msg.parts {
                if let MessagePart::ToolCall {
                    tool_id: tid,
                    status,
                    ..
                } = part
                {
                    if tid == tool_id {
                        *status = ToolStatus::Done {
                            success,
                            output,
                            duration_ms,
                        };
                        break;
                    }
                }
            }
        }
    }

    pub fn finalize_response(&mut self, input_tokens: u32, output_tokens: u32) {
        self.flush_streaming_part();
        self.input_tokens += input_tokens;
        self.output_tokens += output_tokens;
    }

    pub fn add_system_message(&mut self, text: String) {
        self.messages.push(Message {
            role: Role::System,
            parts: vec![MessagePart::Text(text)],
        });
    }

    pub fn set_status(&mut self, msg: String) {
        self.status_message = Some((msg, Instant::now()));
    }

    pub fn scroll_to_bottom(&mut self) {
        self.scroll_offset = 0;
    }

    pub fn scroll_up(&mut self, amount: u16) {
        self.scroll_offset = self.scroll_offset.saturating_add(amount);
    }

    pub fn scroll_down(&mut self, amount: u16) {
        self.scroll_offset = self.scroll_offset.saturating_sub(amount);
    }

    pub fn total_tokens(&self) -> u32 {
        self.input_tokens + self.output_tokens
    }

    pub fn context_percent(&self) -> f32 {
        if self.context_length == 0 {
            return 0.0;
        }
        (self.input_tokens as f32 / self.context_length as f32) * 100.0
    }

    pub fn tick_spinner(&mut self) {
        if self.last_spinner_tick.elapsed().as_millis() >= 120 {
            self.spinner_frame = (self.spinner_frame + 1) % SPINNER_FRAMES.len();
            self.last_spinner_tick = Instant::now();
        }
    }
}

// ── Layout mode ──────────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum LayoutMode {
    Split { direction: Direction },
    Tabs,
}

impl Default for LayoutMode {
    fn default() -> Self {
        LayoutMode::Tabs
    }
}

// ── MultiApp (global state) ──────────────────────────────────────────────

pub struct MultiApp {
    pub panes: Vec<AgentPane>,
    pub focused: u8,
    pub layout_mode: LayoutMode,
    pub broadcast_mode: bool,

    // Global state
    pub running: bool,
    pub active_pane: ActivePane,
    pub show_thinking: bool,
    pub working_dir: String,
}

impl MultiApp {
    pub fn new() -> Self {
        let cwd = std::env::current_dir()
            .map(|p| p.display().to_string())
            .unwrap_or_else(|_| ".".into());

        let initial_pane = AgentPane::new(0);

        Self {
            panes: vec![initial_pane],
            focused: 0,
            layout_mode: LayoutMode::default(),
            broadcast_mode: false,
            running: true,
            active_pane: ActivePane::Input,
            show_thinking: false,
            working_dir: cwd,
        }
    }

    /// Get a reference to the currently focused pane.
    pub fn focused_pane(&self) -> &AgentPane {
        &self.panes[self.focused as usize]
    }

    /// Get a mutable reference to the currently focused pane.
    pub fn focused_pane_mut(&mut self) -> &mut AgentPane {
        &mut self.panes[self.focused as usize]
    }

    /// Spawn a new agent pane and return its id.
    pub fn spawn_pane(&mut self) -> u8 {
        let id = self.panes.len() as u8;
        self.panes.push(AgentPane::new(id));
        id
    }

    /// Close a pane by index. Returns false if it's the last pane (won't close).
    pub fn close_pane(&mut self, id: u8) -> bool {
        if self.panes.len() <= 1 {
            return false;
        }
        let idx = id as usize;
        if idx >= self.panes.len() {
            return false;
        }
        self.panes.remove(idx);
        // Re-assign ids to keep them contiguous
        for (i, pane) in self.panes.iter_mut().enumerate() {
            pane.id = i as u8;
        }
        // Adjust focus
        if self.focused >= self.panes.len() as u8 {
            self.focused = (self.panes.len() - 1) as u8;
        }
        true
    }

    /// Switch focus to the next pane (wraps around).
    pub fn next_pane(&mut self) {
        if self.panes.len() > 1 {
            self.focused = (self.focused + 1) % self.panes.len() as u8;
            self.panes[self.focused as usize].unread = false;
        }
    }

    /// Switch focus to the previous pane (wraps around).
    pub fn prev_pane(&mut self) {
        if self.panes.len() > 1 {
            if self.focused == 0 {
                self.focused = (self.panes.len() - 1) as u8;
            } else {
                self.focused -= 1;
            }
            self.panes[self.focused as usize].unread = false;
        }
    }

    /// Find a pane by name (returns its index).
    pub fn pane_by_name(&self, name: &str) -> Option<u8> {
        self.panes.iter().find(|p| p.name == name).map(|p| p.id)
    }

    /// Number of panes.
    pub fn pane_count(&self) -> usize {
        self.panes.len()
    }
}

// Deref to focused AgentPane for backward compatibility.
// This lets existing code like `app.messages`, `app.agent_running`, etc. keep working
// when there's only one pane (or when operating on the focused pane).
impl std::ops::Deref for MultiApp {
    type Target = AgentPane;

    fn deref(&self) -> &AgentPane {
        self.focused_pane()
    }
}

impl std::ops::DerefMut for MultiApp {
    fn deref_mut(&mut self) -> &mut AgentPane {
        self.focused_pane_mut()
    }
}

/// Backward compatibility alias.
pub type App = MultiApp;

pub const SPINNER_FRAMES: &[&str] = &["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

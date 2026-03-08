use ratatui::{
    prelude::*,
    widgets::{Block, Borders, Paragraph, Scrollbar, ScrollbarOrientation, ScrollbarState, Wrap},
};

use crate::app::{Message, MessagePart, Role, ToolStatus, SPINNER_FRAMES};
use crate::colors;
use crate::ui;

// ── Placeholder types ────────────────────────────────────────────────────
//
// These will be replaced when the app.rs refactor lands with AgentPane + MultiApp.

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum LayoutMode {
    Vertical,
    Horizontal,
}

impl LayoutMode {
    pub fn direction(self) -> Direction {
        match self {
            LayoutMode::Vertical => Direction::Horizontal, // vertical splits = horizontal layout
            LayoutMode::Horizontal => Direction::Vertical,
        }
    }
}

/// Per-agent pane state. Mirrors the subset of App fields needed for rendering.
pub struct PaneState {
    pub name: String,
    pub messages: Vec<Message>,
    pub scroll_offset: u16,
    pub history_height: u16,

    pub model: String,
    pub input_tokens: u32,
    pub output_tokens: u32,
    pub context_length: u32,

    pub agent_running: bool,
    pub loop_state: String,
    pub loop_iteration: u32,
    pub streaming_text: String,
    pub is_thinking: bool,
    pub show_thinking: bool,

    pub spinner_frame: usize,
    pub status_message: Option<(String, std::time::Instant)>,
    pub has_unread: bool,
}

impl PaneState {
    pub fn total_tokens(&self) -> u32 {
        self.input_tokens + self.output_tokens
    }

    pub fn context_percent(&self) -> f32 {
        if self.context_length == 0 {
            return 0.0;
        }
        (self.input_tokens as f32 / self.context_length as f32) * 100.0
    }
}

/// State for the multi-pane application.
pub struct MultiAppState {
    pub panes: Vec<PaneState>,
    pub focused: usize,
    pub layout_mode: LayoutMode,
    pub broadcast_mode: bool,
    pub global_model: String,
}

impl MultiAppState {
    pub fn total_tokens_all(&self) -> u32 {
        self.panes.iter().map(|p| p.total_tokens()).sum()
    }
}

// ── Internal layout for a single pane ────────────────────────────────────

struct PaneLayout {
    history: Rect,
    spinner: Rect,
    input: Option<Rect>,
}

fn build_pane_layout(area: Rect, is_focused: bool) -> PaneLayout {
    if is_focused {
        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Min(3),    // history
                Constraint::Length(1), // spinner line
                Constraint::Length(3), // input area
            ])
            .split(area);

        PaneLayout {
            history: chunks[0],
            spinner: chunks[1],
            input: Some(chunks[2]),
        }
    } else {
        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Min(3),    // history
                Constraint::Length(1), // spinner line
            ])
            .split(area);

        PaneLayout {
            history: chunks[0],
            spinner: chunks[1],
            input: None,
        }
    }
}

// ── Public render functions ──────────────────────────────────────────────

/// Render split-pane layout: N equal columns (or rows) with a shared status bar.
pub fn render_split(
    frame: &mut Frame,
    state: &mut MultiAppState,
    textareas: &[tui_textarea::TextArea],
) {
    let area = frame.area();
    let n = state.panes.len().max(1);

    // Reserve bottom row for global status bar
    let vertical = Layout::vertical([Constraint::Min(0), Constraint::Length(1)]);
    let [main_area, status_area] = vertical.areas(area);

    // Split main area into N equal sections
    let constraints: Vec<Constraint> = (0..n)
        .map(|_| Constraint::Ratio(1, n as u32))
        .collect();

    let pane_areas = Layout::default()
        .direction(state.layout_mode.direction())
        .constraints(constraints)
        .split(main_area);

    for (i, pane_area) in pane_areas.iter().enumerate() {
        let is_focused = state.focused == i;
        let pane = &mut state.panes[i];

        // Pane border
        let border_color = if is_focused {
            colors::GOLD
        } else {
            colors::DIM
        };

        let title = build_pane_title(&pane.name, is_focused, pane.agent_running, pane.has_unread);

        let block = Block::default()
            .borders(Borders::ALL)
            .border_style(Style::default().fg(border_color))
            .title(Line::from(title));

        let inner = block.inner(*pane_area);
        frame.render_widget(block, *pane_area);

        let layout = build_pane_layout(inner, is_focused);

        render_pane_inner(pane, frame, &layout);

        if is_focused {
            if let Some(input_rect) = layout.input {
                if let Some(ta) = textareas.get(i) {
                    render_pane_input(pane, frame, input_rect, ta);
                }
            }
        }
    }

    render_global_status_bar(state, frame, status_area);
}

/// Render tab-mode layout: tab bar at top, focused pane full-width below,
/// global status bar at the bottom.
pub fn render_tabs(
    frame: &mut Frame,
    state: &mut MultiAppState,
    textareas: &[tui_textarea::TextArea],
) {
    let area = frame.area();

    // Tab bar (1 row) + main content + status bar (1 row)
    let vertical = Layout::vertical([
        Constraint::Length(1),
        Constraint::Min(6),
        Constraint::Length(1),
    ]);
    let [tab_area, content_area, status_area] = vertical.areas(area);

    // Render tab bar
    render_tab_bar(state, frame, tab_area);

    // Render the focused pane full-width using the standard single-pane ui functions.
    // We delegate to the existing ui.rs layout for the content area, but we need an
    // App-like interface. Instead, use render_pane_inner with a focused layout.
    if let Some(pane) = state.panes.get_mut(state.focused) {
        let layout = build_pane_layout(content_area, true);

        render_pane_inner(pane, frame, &layout);

        if let Some(input_rect) = layout.input {
            if let Some(ta) = textareas.get(state.focused) {
                render_pane_input(pane, frame, input_rect, ta);
            }
        }
    }

    render_global_status_bar(state, frame, status_area);
}

/// Render a single pane's history + spinner into the given layout areas.
/// Operates on PaneState directly so it works with any layout arrangement.
pub fn render_pane_inner(pane: &mut PaneState, frame: &mut Frame, layout: &PaneLayout) {
    render_pane_history(pane, frame, layout.history);
    render_pane_spinner(pane, frame, layout.spinner);
}

/// Global status bar spanning the full terminal width.
pub fn render_global_status_bar(state: &MultiAppState, frame: &mut Frame, area: Rect) {
    let model_display = if state.global_model.is_empty() {
        "no model".to_string()
    } else if state.global_model.len() > 24 {
        format!("{}...", &state.global_model[..21])
    } else {
        state.global_model.clone()
    };

    let total = state.total_tokens_all();
    let agent_count = state.panes.len();

    let broadcast_span = if state.broadcast_mode {
        Span::styled(" BROADCAST ", Style::default().fg(Color::Black).bg(colors::WARNING).bold())
    } else {
        Span::raw("")
    };

    let line = Line::from(vec![
        Span::styled(
            format!(" {model_display}"),
            Style::default().fg(colors::DIM),
        ),
        Span::styled(" | ", Style::default().fg(colors::SEPARATOR)),
        Span::styled(
            format!("{total}"),
            Style::default().fg(colors::INFO),
        ),
        Span::styled(" tokens", Style::default().fg(colors::DIM)),
        Span::styled(" | ", Style::default().fg(colors::SEPARATOR)),
        Span::styled(
            format!("{agent_count} agent{}", if agent_count != 1 { "s" } else { "" }),
            Style::default().fg(colors::CREAM),
        ),
        Span::styled(" | ", Style::default().fg(colors::SEPARATOR)),
        broadcast_span,
        Span::styled(
            " Ctrl+<-/-> focus  Ctrl+T tabs/split",
            Style::default().fg(colors::DIM),
        ),
    ]);

    frame.render_widget(Paragraph::new(line), area);
}

// ── Private helpers ──────────────────────────────────────────────────────

fn build_pane_title<'a>(
    name: &str,
    is_focused: bool,
    agent_running: bool,
    has_unread: bool,
) -> Vec<Span<'a>> {
    let mut spans = Vec::with_capacity(4);

    spans.push(Span::styled(" ", Style::default()));

    let name_style = if is_focused {
        Style::default().fg(colors::GOLD).bold()
    } else {
        Style::default().fg(colors::DIM)
    };
    spans.push(Span::styled(name.to_string(), name_style));

    if is_focused {
        spans.push(Span::styled(
            " (focused)".to_string(),
            Style::default().fg(colors::GOLD),
        ));
    } else {
        if agent_running {
            spans.push(Span::styled(
                " *".to_string(),
                Style::default().fg(colors::AMBER),
            ));
        }
        if has_unread {
            spans.push(Span::styled(
                " .".to_string(),
                Style::default().fg(colors::INFO),
            ));
        }
    }

    spans.push(Span::styled(" ", Style::default()));
    spans
}

fn render_tab_bar(state: &MultiAppState, frame: &mut Frame, area: Rect) {
    let mut spans: Vec<Span> = Vec::new();

    for (i, pane) in state.panes.iter().enumerate() {
        let is_active = state.focused == i;

        if i > 0 {
            spans.push(Span::styled(" | ", Style::default().fg(colors::SEPARATOR)));
        }

        if is_active {
            spans.push(Span::styled(
                format!("[{}]", pane.name),
                Style::default().fg(colors::GOLD).bold(),
            ));
        } else {
            let mut label = pane.name.clone();
            if pane.agent_running {
                let spinner = SPINNER_FRAMES[pane.spinner_frame];
                label = format!("{} {spinner}", label);
            }
            if pane.has_unread {
                label = format!("{label} .");
            }
            spans.push(Span::styled(label, Style::default().fg(colors::DIM)));
        }
    }

    // "+" button to spawn new agent
    spans.push(Span::styled(" | ", Style::default().fg(colors::SEPARATOR)));
    spans.push(Span::styled("+", Style::default().fg(colors::BRONZE)));

    let line = Line::from(spans);
    let bar = Paragraph::new(line).style(Style::default().bg(Color::Rgb(0x1A, 0x1A, 0x1A)));
    frame.render_widget(bar, area);
}

fn render_pane_history(pane: &mut PaneState, frame: &mut Frame, area: Rect) {
    pane.history_height = area.height;

    let mut lines: Vec<Line> = Vec::new();

    for msg in &pane.messages {
        lines.extend(render_pane_message(msg, area.width as usize, pane.show_thinking));
        lines.push(Line::default());
    }

    // Streaming text (not yet finalized into a message)
    if !pane.streaming_text.is_empty() {
        let style = if pane.is_thinking {
            Style::default().fg(colors::THINK_BLOCK).italic().dim()
        } else {
            Style::default().fg(colors::CREAM)
        };
        for line_str in pane.streaming_text.lines() {
            lines.push(Line::styled(line_str.to_string(), style));
        }
    }

    let total_lines = lines.len() as u16;
    let visible = area.height;
    let max_scroll = total_lines.saturating_sub(visible);
    let scroll = if pane.scroll_offset == 0 {
        max_scroll // auto-scroll to bottom
    } else {
        max_scroll.saturating_sub(pane.scroll_offset)
    };

    let para = Paragraph::new(lines)
        .scroll((scroll, 0))
        .wrap(Wrap { trim: false });

    frame.render_widget(para, area);

    // Scrollbar
    if total_lines > visible {
        let mut scrollbar_state =
            ScrollbarState::new(total_lines as usize).position(scroll as usize);
        let scrollbar = Scrollbar::new(ScrollbarOrientation::VerticalRight)
            .style(Style::default().fg(colors::DIM));
        frame.render_stateful_widget(
            scrollbar,
            area.inner(Margin {
                horizontal: 0,
                vertical: 0,
            }),
            &mut scrollbar_state,
        );
    }
}

fn render_pane_message(msg: &Message, width: usize, show_thinking: bool) -> Vec<Line<'static>> {
    let mut lines = Vec::new();

    match msg.role {
        Role::User => {
            lines.push(Line::styled(
                " You ".to_string(),
                Style::default().fg(Color::White).bg(colors::USER_MSG).bold(),
            ));
            for part in &msg.parts {
                if let MessagePart::Text(text) = part {
                    for s in text.lines() {
                        lines.push(Line::styled(
                            format!("  {s}"),
                            Style::default().fg(colors::CREAM),
                        ));
                    }
                }
            }
        }
        Role::Assistant => {
            lines.push(Line::from(vec![
                Span::styled("--", Style::default().fg(colors::GOLD)),
                Span::styled(" Hermes ", Style::default().fg(colors::GOLD).bold()),
                Span::styled(
                    "-".repeat(width.saturating_sub(12)),
                    Style::default().fg(colors::GOLD),
                ),
            ]));
            for part in &msg.parts {
                match part {
                    MessagePart::Text(text) => {
                        for s in text.lines() {
                            lines.push(Line::styled(
                                format!("  {s}"),
                                Style::default().fg(colors::CREAM),
                            ));
                        }
                    }
                    MessagePart::ThinkBlock(text) => {
                        if show_thinking {
                            lines.push(Line::styled(
                                "  ~ thinking ~",
                                Style::default().fg(colors::THINK_BLOCK).italic(),
                            ));
                            for s in text.lines() {
                                lines.push(Line::styled(
                                    format!("    {s}"),
                                    Style::default().fg(colors::THINK_BLOCK).dim().italic(),
                                ));
                            }
                        } else {
                            lines.push(Line::styled(
                                "  [... thinking ...]",
                                Style::default().fg(colors::THINK_BLOCK).dim(),
                            ));
                        }
                    }
                    MessagePart::ToolCall {
                        tool_name,
                        args_preview,
                        status,
                        ..
                    } => {
                        lines.push(render_tool_line(tool_name, args_preview, status));
                    }
                }
            }
            lines.push(Line::styled(
                "-".repeat(width),
                Style::default().fg(colors::GOLD),
            ));
        }
        Role::System => {
            for part in &msg.parts {
                if let MessagePart::Text(text) = part {
                    for s in text.lines() {
                        lines.push(Line::styled(
                            format!("  {s}"),
                            Style::default().fg(colors::DIM).italic(),
                        ));
                    }
                }
            }
        }
    }

    lines
}

fn render_tool_line<'a>(tool_name: &str, args_preview: &str, status: &ToolStatus) -> Line<'a> {
    match status {
        ToolStatus::Running(started) => {
            let elapsed = started.elapsed().as_secs_f32();
            Line::from(vec![
                Span::styled("  | ", Style::default().fg(colors::DIM)),
                Span::styled("* ", Style::default().fg(colors::TOOL_RUNNING)),
                Span::styled(
                    format!("{tool_name:<12}"),
                    Style::default().fg(colors::TOOL_RUNNING).bold(),
                ),
                Span::styled(args_preview.to_string(), Style::default().fg(colors::DIM)),
                Span::styled(
                    format!("  ({elapsed:.1}s)"),
                    Style::default().fg(colors::DIM),
                ),
            ])
        }
        ToolStatus::Done {
            success,
            output,
            duration_ms,
        } => {
            let (icon, color) = if *success {
                ("v", colors::TOOL_DONE)
            } else {
                ("x", colors::TOOL_FAIL)
            };
            let dur = *duration_ms as f32 / 1000.0;
            let preview = if output.len() > 40 {
                format!("{}...", &output[..37])
            } else {
                output.clone()
            };
            Line::from(vec![
                Span::styled("  | ", Style::default().fg(colors::DIM)),
                Span::styled(format!("{icon} "), Style::default().fg(color)),
                Span::styled(
                    format!("{tool_name:<12}"),
                    Style::default().fg(color).bold(),
                ),
                Span::styled(preview, Style::default().fg(colors::DIM)),
                Span::styled(
                    format!("  ({dur:.1}s)"),
                    Style::default().fg(colors::DIM),
                ),
            ])
        }
    }
}

fn render_pane_spinner(pane: &PaneState, frame: &mut Frame, area: Rect) {
    let content = if pane.agent_running {
        let spinner = SPINNER_FRAMES[pane.spinner_frame];
        let state_info = if pane.loop_state.is_empty() {
            String::new()
        } else {
            format!(" | {}", pane.loop_state)
        };
        Line::from(vec![
            Span::styled(
                format!(" {spinner} "),
                Style::default().fg(colors::AMBER).bold(),
            ),
            Span::styled(
                format!("Iteration {}", pane.loop_iteration),
                Style::default().fg(colors::CREAM),
            ),
            Span::styled(state_info, Style::default().fg(colors::DIM)),
        ])
    } else if let Some((ref msg, when)) = pane.status_message {
        if when.elapsed().as_secs() < 10 {
            Line::styled(format!(" {msg}"), Style::default().fg(colors::DIM).italic())
        } else {
            Line::styled(" Ready", Style::default().fg(colors::DIM).italic())
        }
    } else {
        Line::styled(" Ready", Style::default().fg(colors::DIM).italic())
    };

    frame.render_widget(Paragraph::new(content), area);
}

fn render_pane_input(
    pane: &PaneState,
    frame: &mut Frame,
    area: Rect,
    textarea: &tui_textarea::TextArea,
) {
    let border_style = Style::default().fg(colors::BRONZE);

    let hint = if pane.agent_running {
        " Enter to interrupt "
    } else {
        " Enter to send "
    };

    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(Span::styled(
            hint,
            Style::default().fg(colors::DIM).italic(),
        ))
        .title_position(ratatui::widgets::block::Position::Bottom);

    let inner = block.inner(area);
    frame.render_widget(block, area);
    frame.render_widget(textarea, inner);
}

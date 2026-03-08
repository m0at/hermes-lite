use ratatui::{
    prelude::*,
    widgets::{Block, Borders, Paragraph, Scrollbar, ScrollbarOrientation, ScrollbarState, Wrap},
};

use crate::app::{AgentPane, App, LayoutMode, Message, MessagePart, Role, ToolStatus, SPINNER_FRAMES, DOTS_FRAMES};
use crate::colors;

// ── Internal layout for a single pane ────────────────────────────────────

struct PaneLayout {
    history: Rect,
    spinner: Rect,
    input: Option<Rect>,
}

fn build_pane_layout(area: Rect, is_focused: bool, input_lines: usize) -> PaneLayout {
    if is_focused {
        // +2 for top/bottom border, clamped to [3, 10]
        let input_height = (input_lines + 2).max(3).min(10) as u16;
        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Min(3),              // history
                Constraint::Length(1),           // spinner line
                Constraint::Length(input_height), // input area (grows with content)
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
    app: &mut App,
    textareas: &[tui_textarea::TextArea],
) {
    let area = frame.area();
    let n = app.panes.len().max(1);

    // Reserve bottom row for global status bar
    let vertical = Layout::vertical([Constraint::Min(0), Constraint::Length(1)]);
    let [main_area, status_area] = vertical.areas(area);

    // Split main area into N equal sections
    let constraints: Vec<Constraint> = (0..n)
        .map(|_| Constraint::Ratio(1, n as u32))
        .collect();

    let direction = match app.layout_mode {
        LayoutMode::Split { direction } => direction,
        LayoutMode::Tabs => Direction::Horizontal, // fallback
    };

    let pane_areas = Layout::default()
        .direction(direction)
        .constraints(constraints)
        .split(main_area);

    let focused = app.focused as usize;
    let show_thinking = app.show_thinking;

    for (i, pane_area) in pane_areas.iter().enumerate() {
        let is_focused = focused == i;
        let pane = &mut app.panes[i];

        // Pane border
        let border_color = if is_focused {
            colors::GOLD
        } else {
            colors::DIM
        };

        let title = build_pane_title(&pane.name, is_focused, pane.agent_running, pane.unread);

        let block = Block::default()
            .borders(Borders::ALL)
            .border_style(Style::default().fg(border_color))
            .title(Line::from(title));

        let inner = block.inner(*pane_area);
        frame.render_widget(block, *pane_area);

        let input_lines = if is_focused {
            textareas.get(i).map_or(1, |ta| ta.lines().len().max(1))
        } else {
            1
        };
        let layout = build_pane_layout(inner, is_focused, input_lines);

        render_pane_inner(pane, frame, &layout, show_thinking);

        if is_focused {
            if let Some(input_rect) = layout.input {
                if let Some(ta) = textareas.get(i) {
                    render_pane_input(pane, frame, input_rect, ta);
                }
            }
        }
    }

    render_global_status_bar(app, frame, status_area);
}

/// Render tab-mode layout: tab bar at top, focused pane full-width below,
/// global status bar at the bottom.
pub fn render_tabs(
    frame: &mut Frame,
    app: &mut App,
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
    render_tab_bar(app, frame, tab_area);

    // Render the focused pane full-width
    let focused = app.focused as usize;
    let show_thinking = app.show_thinking;
    if let Some(pane) = app.panes.get_mut(focused) {
        let input_lines = textareas.get(focused).map_or(1, |ta| ta.lines().len().max(1));
        let layout = build_pane_layout(content_area, true, input_lines);

        render_pane_inner(pane, frame, &layout, show_thinking);

        if let Some(input_rect) = layout.input {
            if let Some(ta) = textareas.get(focused) {
                render_pane_input(pane, frame, input_rect, ta);
            }
        }
    }

    render_global_status_bar(app, frame, status_area);
}

/// Render a single pane's history + spinner.
fn render_pane_inner(pane: &mut AgentPane, frame: &mut Frame, layout: &PaneLayout, show_thinking: bool) {
    render_pane_history(pane, frame, layout.history, show_thinking);
    render_pane_spinner(pane, frame, layout.spinner);
}

/// Global status bar spanning the full terminal width.
fn render_global_status_bar(app: &App, frame: &mut Frame, area: Rect) {
    let model = &app.focused_pane().model;
    let model_display = if model.is_empty() {
        "no model".to_string()
    } else if model.len() > 24 {
        format!("{}...", &model[..21])
    } else {
        model.clone()
    };

    let total: u32 = app.panes.iter().map(|p| p.total_tokens()).sum();
    let agent_count = app.panes.len();

    let broadcast_span = if app.broadcast_mode {
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
            " Ctrl+←/→ focus  /split /tabs /agents",
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

fn render_tab_bar(app: &App, frame: &mut Frame, area: Rect) {
    let mut spans: Vec<Span> = Vec::new();

    for (i, pane) in app.panes.iter().enumerate() {
        let is_active = app.focused as usize == i;

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
            if pane.unread {
                label = format!("{label} .");
            }
            spans.push(Span::styled(label, Style::default().fg(colors::DIM)));
        }
    }

    // "+" hint
    spans.push(Span::styled(" | ", Style::default().fg(colors::SEPARATOR)));
    spans.push(Span::styled("+", Style::default().fg(colors::BRONZE)));

    let line = Line::from(spans);
    let bar = Paragraph::new(line).style(Style::default().bg(Color::Rgb(0x1A, 0x1A, 0x1A)));
    frame.render_widget(bar, area);
}

fn render_pane_history(pane: &mut AgentPane, frame: &mut Frame, area: Rect, show_thinking: bool) {
    pane.history_height = area.height;

    let mut lines: Vec<Line> = Vec::new();

    for msg in &pane.messages {
        lines.extend(render_pane_message(msg, area.width as usize, show_thinking));
        lines.push(Line::default());
    }

    // Streaming text
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

    let wrap_width = area.width as usize;
    let total_lines: u16 = lines
        .iter()
        .map(|line| {
            let w = line.width();
            if w == 0 || wrap_width == 0 {
                1u16
            } else {
                ((w as u16).saturating_sub(1) / wrap_width as u16) + 1
            }
        })
        .sum();
    let visible = area.height;
    let max_scroll = total_lines.saturating_sub(visible);
    let scroll = if pane.scroll_offset == 0 {
        max_scroll
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
                Span::styled("──", Style::default().fg(colors::GOLD)),
                Span::styled(" Hermes ", Style::default().fg(colors::GOLD).bold()),
                Span::styled(
                    "─".repeat(width.saturating_sub(12)),
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
                "─".repeat(width),
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

fn render_pane_spinner(pane: &AgentPane, frame: &mut Frame, area: Rect) {
    let content = if pane.agent_running {
        let spinner = SPINNER_FRAMES[pane.spinner_frame % SPINNER_FRAMES.len()];
        let dots = DOTS_FRAMES[pane.dots_frame % DOTS_FRAMES.len()];
        let state_info = if pane.loop_state.is_empty() {
            String::new()
        } else {
            format!(" | {}", pane.loop_state)
        };
        let spinner_color = if pane.spinner_frame % 2 == 0 {
            colors::AMBER
        } else {
            colors::GOLD
        };
        Line::from(vec![
            Span::styled(
                format!(" {spinner} "),
                Style::default().fg(spinner_color).bold(),
            ),
            Span::styled(
                format!("Iteration {}", pane.loop_iteration),
                Style::default().fg(colors::CREAM),
            ),
            Span::styled(state_info, Style::default().fg(colors::DIM)),
            Span::styled(
                format!(" {dots}"),
                Style::default().fg(colors::AMBER),
            ),
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
    pane: &AgentPane,
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

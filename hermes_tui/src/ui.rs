use ratatui::{
    prelude::*,
    widgets::{
        block::Position as TitlePosition, Block, Borders, Paragraph, Scrollbar,
        ScrollbarOrientation, ScrollbarState, Wrap,
    },
};

use crate::app::{App, ActivePane, Message, MessagePart, Role, ToolStatus, SPINNER_FRAMES};
use crate::colors;

// ── Layout ───────────────────────────────────────────────────────────────

pub struct LayoutAreas {
    pub history: Rect,
    pub separator1: Rect,
    pub spinner: Rect,
    pub separator2: Rect,
    pub input: Rect,
    pub status_bar: Rect,
}

pub fn build_layout(area: Rect) -> LayoutAreas {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Min(6),     // history
            Constraint::Length(1),  // separator
            Constraint::Length(1),  // spinner/status
            Constraint::Length(1),  // separator
            Constraint::Length(5),  // input area
            Constraint::Length(1),  // status bar
        ])
        .split(area);

    LayoutAreas {
        history: chunks[0],
        separator1: chunks[1],
        spinner: chunks[2],
        separator2: chunks[3],
        input: chunks[4],
        status_bar: chunks[5],
    }
}

// ── Render functions ─────────────────────────────────────────────────────

pub fn render_history(app: &mut App, frame: &mut Frame, area: Rect) {
    app.history_height = area.height;

    let mut lines: Vec<Line> = Vec::new();

    if app.messages.is_empty() {
        lines.extend(render_welcome(area.width));
    }

    for msg in &app.messages {
        lines.extend(render_message(msg, area.width as usize, app.show_thinking));
        lines.push(Line::default()); // gap between messages
    }

    // Streaming text (not yet finalized)
    if !app.streaming_text.is_empty() {
        let style = if app.is_thinking {
            Style::default().fg(colors::THINK_BLOCK).italic().dim()
        } else {
            Style::default().fg(colors::CREAM)
        };
        for line_str in app.streaming_text.lines() {
            lines.push(Line::styled(line_str.to_string(), style));
        }
    }

    let total_lines = lines.len() as u16;
    let visible = area.height;
    let max_scroll = total_lines.saturating_sub(visible);
    let scroll = if app.scroll_offset == 0 {
        max_scroll // auto-scroll to bottom
    } else {
        max_scroll.saturating_sub(app.scroll_offset)
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

fn render_welcome(width: u16) -> Vec<Line<'static>> {
    let mut lines = Vec::new();
    lines.push(Line::default());

    // Compact banner
    let banner_lines = [
        "╔═══════════════════════════════════════════════╗",
        "║      HERMES-LITE  ·  Local Coding Agent      ║",
        "╚═══════════════════════════════════════════════╝",
    ];
    for bl in banner_lines {
        let centered = format!("{:^width$}", bl, width = width as usize);
        lines.push(Line::styled(centered, Style::default().fg(colors::GOLD).bold()));
    }

    lines.push(Line::default());
    lines.push(Line::styled(
        "  Type a message to begin, or /help for commands.",
        Style::default().fg(colors::CREAM).dim(),
    ));
    lines.push(Line::default());
    lines
}

fn render_message(msg: &Message, width: usize, show_thinking: bool) -> Vec<Line<'static>> {
    let mut lines = Vec::new();

    match msg.role {
        Role::User => {
            lines.push(Line::styled(
                " You ".to_string(),
                Style::default().fg(Color::White).bg(colors::USER_MSG).bold(),
            ));
            for part in &msg.parts {
                if let MessagePart::Text(text) = part {
                    for line_str in text.lines() {
                        lines.push(Line::styled(
                            format!("  {line_str}"),
                            Style::default().fg(colors::CREAM),
                        ));
                    }
                }
            }
        }
        Role::Assistant => {
            lines.push(Line::from(vec![
                Span::styled("──", Style::default().fg(colors::GOLD)),
                Span::styled(" ⚕ Hermes ", Style::default().fg(colors::GOLD).bold()),
                Span::styled(
                    "─".repeat(width.saturating_sub(15)),
                    Style::default().fg(colors::GOLD),
                ),
            ]));
            for part in &msg.parts {
                match part {
                    MessagePart::Text(text) => {
                        for line_str in text.lines() {
                            lines.push(Line::styled(
                                format!("  {line_str}"),
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
                            for line_str in text.lines() {
                                lines.push(Line::styled(
                                    format!("    {line_str}"),
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
                        lines.push(render_tool_call_line(tool_name, args_preview, status));
                    }
                }
            }
            // Bottom border
            lines.push(Line::styled(
                "─".repeat(width),
                Style::default().fg(colors::GOLD),
            ));
        }
        Role::System => {
            for part in &msg.parts {
                if let MessagePart::Text(text) = part {
                    for line_str in text.lines() {
                        lines.push(Line::styled(
                            format!("  {line_str}"),
                            Style::default().fg(colors::DIM).italic(),
                        ));
                    }
                }
            }
        }
    }

    lines
}

fn render_tool_call_line<'a>(
    tool_name: &str,
    args_preview: &str,
    status: &ToolStatus,
) -> Line<'a> {
    match status {
        ToolStatus::Running(started) => {
            let elapsed = started.elapsed().as_secs_f32();
            Line::from(vec![
                Span::styled("  ┊ ", Style::default().fg(colors::DIM)),
                Span::styled("⠿ ", Style::default().fg(colors::TOOL_RUNNING)),
                Span::styled(
                    format!("{tool_name:<12}"),
                    Style::default().fg(colors::TOOL_RUNNING).bold(),
                ),
                Span::styled(
                    args_preview.to_string(),
                    Style::default().fg(colors::DIM),
                ),
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
                ("✓", colors::TOOL_DONE)
            } else {
                ("✗", colors::TOOL_FAIL)
            };
            let dur = *duration_ms as f32 / 1000.0;
            let preview = if output.len() > 40 {
                format!("{}…", &output[..39])
            } else {
                output.clone()
            };
            Line::from(vec![
                Span::styled("  ┊ ", Style::default().fg(colors::DIM)),
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

pub fn render_separator(frame: &mut Frame, area: Rect) {
    let sep = Paragraph::new(Line::styled(
        "─".repeat(area.width as usize),
        Style::default().fg(colors::SEPARATOR),
    ));
    frame.render_widget(sep, area);
}

pub fn render_spinner(app: &App, frame: &mut Frame, area: Rect) {
    let content = if app.agent_running {
        let spinner = SPINNER_FRAMES[app.spinner_frame];
        let state_info = if app.loop_state.is_empty() {
            String::new()
        } else {
            format!(" │ {}", app.loop_state)
        };
        Line::from(vec![
            Span::styled(
                format!(" {spinner} "),
                Style::default().fg(colors::AMBER).bold(),
            ),
            Span::styled(
                format!("Iteration {}", app.loop_iteration),
                Style::default().fg(colors::CREAM),
            ),
            Span::styled(state_info, Style::default().fg(colors::DIM)),
        ])
    } else if let Some((ref msg, when)) = app.status_message {
        if when.elapsed().as_secs() < 10 {
            Line::styled(format!(" {msg}"), Style::default().fg(colors::DIM).italic())
        } else {
            Line::styled(
                " Ready",
                Style::default().fg(colors::DIM).italic(),
            )
        }
    } else {
        Line::styled(
            " Ready",
            Style::default().fg(colors::DIM).italic(),
        )
    };

    frame.render_widget(Paragraph::new(content), area);
}

pub fn render_input_area(
    app: &App,
    frame: &mut Frame,
    area: Rect,
    textarea: &tui_textarea::TextArea,
) {
    let border_style = if app.active_pane == ActivePane::Input {
        Style::default().fg(colors::BRONZE)
    } else {
        Style::default().fg(colors::DIM)
    };

    let prompt_hint = if app.agent_running {
        " Enter to interrupt · Ctrl+C to cancel "
    } else {
        " Enter to send · Alt+Enter for newline · /help for commands "
    };

    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(border_style)
        .title(Span::styled(
            prompt_hint,
            Style::default().fg(colors::DIM).italic(),
        ))
        .title_position(TitlePosition::Bottom);

    let inner = block.inner(area);
    frame.render_widget(block, area);

    // Render textarea widget inside
    frame.render_widget(textarea, inner);
}

pub fn render_status_bar(app: &App, frame: &mut Frame, area: Rect) {
    let model_display = if app.model.is_empty() {
        "no model".to_string()
    } else if app.model.len() > 24 {
        format!("{}…", &app.model[..23])
    } else {
        app.model.clone()
    };

    let total = app.total_tokens();
    let pct = app.context_percent();

    let pct_color = if pct < 50.0 {
        colors::SUCCESS
    } else if pct < 75.0 {
        colors::AMBER
    } else if pct < 90.0 {
        colors::WARNING
    } else {
        colors::ERROR
    };

    let line = Line::from(vec![
        Span::styled(
            format!(" {model_display}"),
            Style::default().fg(colors::DIM),
        ),
        Span::styled(" │ ", Style::default().fg(colors::SEPARATOR)),
        Span::styled(
            format!("{total}"),
            Style::default().fg(colors::INFO),
        ),
        Span::styled(" tokens", Style::default().fg(colors::DIM)),
        Span::styled(
            format!(" ({pct:.0}%)"),
            Style::default().fg(pct_color),
        ),
        Span::styled(" │ ", Style::default().fg(colors::SEPARATOR)),
        Span::styled(
            if app.session_id.is_empty() {
                "no session".to_string()
            } else if app.session_id.len() > 16 {
                format!("{}…", &app.session_id[..15])
            } else {
                app.session_id.clone()
            },
            Style::default().fg(colors::DIM),
        ),
    ]);

    frame.render_widget(Paragraph::new(line), area);
}

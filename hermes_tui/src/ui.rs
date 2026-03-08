use ratatui::{
    prelude::*,
    widgets::{
        block::Position as TitlePosition, Block, Borders, Paragraph, Scrollbar,
        ScrollbarOrientation, ScrollbarState, Wrap,
    },
};

use crate::app::{App, ActivePane, ClarifyDialog, Message, MessagePart, Role, ToolStatus, SPINNER_FRAMES, DOTS_FRAMES};
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

    // Count wrapped lines (each line may wrap to multiple visual rows)
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
        let spinner = SPINNER_FRAMES[app.spinner_frame % SPINNER_FRAMES.len()];
        let dots = DOTS_FRAMES[app.dots_frame % DOTS_FRAMES.len()];
        let state_info = if app.loop_state.is_empty() {
            String::new()
        } else {
            format!(" │ {}", app.loop_state)
        };
        // Pulse the spinner color between amber and gold
        let spinner_color = if app.spinner_frame % 2 == 0 {
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
                format!("Iteration {}", app.loop_iteration),
                Style::default().fg(colors::CREAM),
            ),
            Span::styled(state_info, Style::default().fg(colors::DIM)),
            Span::styled(
                format!(" {dots}"),
                Style::default().fg(colors::AMBER),
            ),
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

pub fn render_clarify_dialog(dialog: &ClarifyDialog, frame: &mut Frame, area: Rect) {
    // Center a popup that takes ~60% of screen width, sized to content
    let popup_width = (area.width * 3 / 5).max(40).min(area.width.saturating_sub(4));
    // Height: 3 (border+question) + question lines + choices + input + padding
    let question_lines = dialog.question.lines().count() as u16;
    let choices_lines = if dialog.choices.is_empty() {
        0
    } else {
        dialog.choices.len() as u16 + 1 // +1 for "Choices:" label
    };
    let input_lines = 3u16; // label + input + hint
    let inner_height = question_lines + choices_lines + input_lines + 1; // +1 gap
    let popup_height = (inner_height + 2).min(area.height.saturating_sub(2)); // +2 for borders

    let x = area.x + (area.width.saturating_sub(popup_width)) / 2;
    let y = area.y + (area.height.saturating_sub(popup_height)) / 2;
    let popup_area = Rect::new(x, y, popup_width, popup_height);

    // Clear the popup area background
    frame.render_widget(ratatui::widgets::Clear, popup_area);

    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(colors::AMBER))
        .title(Span::styled(
            " Agent Question ",
            Style::default().fg(colors::GOLD).bold(),
        ))
        .title_position(TitlePosition::Top)
        .title(Span::styled(
            " Enter to submit · Esc to dismiss ",
            Style::default().fg(colors::DIM).italic(),
        ))
        .title_position(TitlePosition::Bottom)
        .style(Style::default().bg(Color::Rgb(0x1a, 0x1a, 0x1a)));
    let inner = block.inner(popup_area);
    frame.render_widget(block, popup_area);

    // Build content lines inside the popup
    let mut lines: Vec<Line> = Vec::new();

    // Question text
    for qline in dialog.question.lines() {
        lines.push(Line::styled(
            format!(" {qline}"),
            Style::default().fg(colors::CREAM).bold(),
        ));
    }
    lines.push(Line::default());

    // Choices (if any)
    if !dialog.choices.is_empty() {
        lines.push(Line::styled(
            " Choices (Up/Down to select):",
            Style::default().fg(colors::DIM).italic(),
        ));
        for (i, choice) in dialog.choices.iter().enumerate() {
            let is_selected = dialog.selected_choice == Some(i);
            let (prefix, style) = if is_selected {
                ("  > ", Style::default().fg(colors::GOLD).bold())
            } else {
                ("    ", Style::default().fg(colors::CREAM))
            };
            lines.push(Line::styled(format!("{prefix}{choice}"), style));
        }
        lines.push(Line::default());
    }

    // Input field
    let input_label = if dialog.choices.is_empty() {
        " Your response:"
    } else {
        " Or type a response:"
    };
    lines.push(Line::styled(
        input_label,
        Style::default().fg(colors::DIM).italic(),
    ));

    // Render input with cursor
    let input_display = if dialog.selected_choice.is_some() && dialog.input.is_empty() {
        // Show placeholder when a choice is selected and no text typed
        Line::styled(
            " (press Enter to confirm selection)",
            Style::default().fg(colors::DIM).italic(),
        )
    } else {
        // Show the input text with a cursor indicator
        let before = &dialog.input[..dialog.cursor];
        let cursor_char = dialog.input[dialog.cursor..].chars().next().unwrap_or(' ');
        let after_cursor = if dialog.cursor < dialog.input.len() {
            let char_len = cursor_char.len_utf8();
            &dialog.input[dialog.cursor + char_len..]
        } else {
            ""
        };
        Line::from(vec![
            Span::styled(format!(" {before}"), Style::default().fg(colors::CREAM)),
            Span::styled(
                cursor_char.to_string(),
                Style::default().fg(Color::Black).bg(colors::CREAM),
            ),
            Span::styled(after_cursor.to_string(), Style::default().fg(colors::CREAM)),
        ])
    };
    lines.push(input_display);

    let para = Paragraph::new(lines).wrap(Wrap { trim: false });
    frame.render_widget(para, inner);
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

pub fn render_help_overlay(frame: &mut Frame, area: Rect) {
    let help_lines = [
        ("General", vec![
            ("/help",      "Toggle this help"),
            ("/clear",     "Clear conversation"),
            ("/new",       "Start fresh conversation"),
            ("/model <m>", "Switch model"),
            ("/thinkon",   "Show thinking blocks"),
            ("/thinkoff",  "Hide thinking blocks"),
            ("/usage",     "Show token usage"),
            ("/context",   "Show context window"),
            ("/quit",      "Exit (also Ctrl+D)"),
        ]),
        ("Multi-Agent", vec![
            ("/split",         "New agent — vertical split"),
            ("/hsplit",        "New agent — horizontal split"),
            ("/tabs",          "Switch to tab layout"),
            ("/close",         "Close focused pane"),
            ("/name <n>",      "Rename focused agent"),
            ("/focus <n>",     "Focus by name or number"),
            ("/broadcast <m>", "Send to all agents"),
            ("/ask <t> <m>",   "Send to agent, pull response back"),
            ("/agents",        "List all agents"),
        ]),
        ("Shortcuts", vec![
            ("Ctrl+←/→",   "Switch panes"),
            ("Alt+1-9",    "Focus pane by number"),
            ("@name msg",  "Route to named agent"),
            ("@name! msg", "Route + pull response back"),
            ("@all msg",   "Broadcast to all"),
            ("Ctrl+C",     "Interrupt / clear input"),
            ("PageUp/Dn",  "Scroll history"),
        ]),
    ];

    // Calculate dimensions
    let mut content_lines: Vec<Line> = Vec::new();
    for (section, items) in &help_lines {
        if !content_lines.is_empty() {
            content_lines.push(Line::default());
        }
        content_lines.push(Line::styled(
            format!(" {section}"),
            Style::default().fg(colors::GOLD).bold(),
        ));
        for (cmd, desc) in items {
            content_lines.push(Line::from(vec![
                Span::styled(format!("  {cmd:<16}"), Style::default().fg(colors::CREAM)),
                Span::styled(format!(" {desc}"), Style::default().fg(colors::DIM)),
            ]));
        }
    }

    let popup_width = 46u16.min(area.width.saturating_sub(4));
    let popup_height = (content_lines.len() as u16 + 2).min(area.height.saturating_sub(2));

    let x = area.x + (area.width.saturating_sub(popup_width)) / 2;
    let y = area.y + (area.height.saturating_sub(popup_height)) / 2;
    let popup_area = Rect::new(x, y, popup_width, popup_height);

    frame.render_widget(ratatui::widgets::Clear, popup_area);

    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(colors::GOLD))
        .title(Span::styled(
            " Help ",
            Style::default().fg(colors::GOLD).bold(),
        ))
        .title_position(TitlePosition::Top)
        .title(Span::styled(
            " Esc or /help to close ",
            Style::default().fg(colors::DIM).italic(),
        ))
        .title_position(TitlePosition::Bottom)
        .style(Style::default().bg(Color::Rgb(0x1a, 0x1a, 0x1a)));

    let inner = block.inner(popup_area);
    frame.render_widget(block, popup_area);
    frame.render_widget(Paragraph::new(content_lines).wrap(Wrap { trim: false }), inner);
}

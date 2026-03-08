#![allow(dead_code)]

mod app;
mod colors;
mod mention;
mod protocol;
mod subprocess;
mod ui;

use std::io;

use crossterm::{
    event::{self, Event, KeyCode, KeyEvent, KeyModifiers},
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
    ExecutableCommand,
};
use ratatui::prelude::*;
use tokio::sync::mpsc;
use tui_textarea::{Input, TextArea};

use app::{ActivePane, App, Role, SlashCommand};
use protocol::{FromAgent, ToAgent};

fn make_textarea<'a>() -> TextArea<'a> {
    let mut ta = TextArea::default();
    ta.set_cursor_line_style(Style::default());
    ta.set_cursor_style(Style::default().fg(colors::CREAM).reversed());
    ta.set_placeholder_text("Type a message...");
    ta.set_placeholder_style(Style::default().fg(colors::DIM).italic());
    ta
}

#[tokio::main]
async fn main() -> io::Result<()> {
    // Terminal setup
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    stdout.execute(EnterAlternateScreen)?;
    let mut terminal = Terminal::new(CrosstermBackend::new(stdout))?;

    let mut app = App::new();
    let mut textarea = make_textarea();

    // Spawn agent subprocess
    let (mut agent_rx, to_agent_tx) = match subprocess::AgentProcess::spawn(
        mpsc::channel::<FromAgent>(1).0,
    )
    .await
    {
        Ok((agent, from_rx)) => {
            // Build a ToAgent sender that serializes and forwards to the agent's stdin writer.
            // We create a channel of ToAgent, and a background task that calls agent.send().
            let (tx, mut rx) = mpsc::channel::<ToAgent>(64);
            tokio::spawn(async move {
                let agent = agent;
                while let Some(msg) = rx.recv().await {
                    if agent.send(&msg).await.is_err() {
                        break;
                    }
                }
                agent.shutdown().await;
            });
            app.set_status("Agent subprocess started".into());
            (Some(from_rx), Some(tx))
        }
        Err(e) => {
            app.add_system_message(format!("Failed to start agent: {e}"));
            app.set_status("No agent — type /quit to exit".into());
            (None, None)
        }
    };

    // Event loop
    while app.running {
        // Render
        terminal.draw(|frame| {
            let area = frame.area();
            let layout = ui::build_layout(area);

            ui::render_history(&mut app, frame, layout.history);
            ui::render_separator(frame, layout.separator1);
            ui::render_spinner(&app, frame, layout.spinner);
            ui::render_separator(frame, layout.separator2);
            ui::render_input_area(&app, frame, layout.input, &textarea);
            ui::render_status_bar(&app, frame, layout.status_bar);

            // Clarify dialog overlay (rendered last so it's on top)
            if let Some(ref dialog) = app.focused_pane().clarify_dialog {
                ui::render_clarify_dialog(dialog, frame, area);
            }
        })?;

        // Tick spinner animation
        if app.agent_running {
            app.tick_spinner();
        }

        // Poll terminal events (50ms tick for spinner animation)
        if event::poll(std::time::Duration::from_millis(50))? {
            match event::read()? {
                Event::Key(key) => handle_key_event(&mut app, &mut textarea, &to_agent_tx, key),
                Event::Resize(_, _) => {} // ratatui handles resize on next draw
                _ => {}
            }
        }

        // Poll agent messages from subprocess
        if let Some(ref mut rx) = agent_rx {
            loop {
                match rx.try_recv() {
                    Ok(msg) => handle_agent_message(&mut app, msg),
                    Err(mpsc::error::TryRecvError::Empty) => break,
                    Err(mpsc::error::TryRecvError::Disconnected) => {
                        // Agent process died
                        if app.agent_running {
                            app.agent_running = false;
                            app.add_system_message("Agent process terminated unexpectedly".into());
                        }
                        app.set_status("Agent disconnected".into());
                        agent_rx = None;
                        break;
                    }
                }
            }
        }
    }

    // Shutdown: notify agent subprocess
    if let Some(tx) = to_agent_tx {
        let _ = tx.try_send(ToAgent::Shutdown);
    }

    // Teardown terminal
    disable_raw_mode()?;
    io::stdout().execute(LeaveAlternateScreen)?;
    Ok(())
}

fn handle_key_event(
    app: &mut App,
    textarea: &mut TextArea,
    to_agent: &Option<mpsc::Sender<ToAgent>>,
    key: KeyEvent,
) {
    // Clarify dialog captures all input when active
    if app.focused_pane().clarify_dialog.is_some() {
        handle_clarify_key(app, to_agent, key);
        return;
    }

    // Global keybindings first
    match (key.code, key.modifiers) {
        // Ctrl+C: interrupt or exit
        (KeyCode::Char('c'), KeyModifiers::CONTROL) => {
            if app.agent_running {
                if let Some(tx) = to_agent {
                    let _ = tx.try_send(ToAgent::Interrupt);
                }
                app.set_status("Interrupting agent...".into());
                app.agent_running = false;
            } else {
                let text = textarea.lines().join("\n");
                if text.is_empty() {
                    app.running = false;
                } else {
                    // Clear input
                    *textarea = make_textarea();
                }
            }
            return;
        }
        // Ctrl+D: exit
        (KeyCode::Char('d'), KeyModifiers::CONTROL) => {
            app.running = false;
            return;
        }
        // Page Up/Down: scroll history
        (KeyCode::PageUp, _) => {
            app.active_pane = ActivePane::History;
            let h = app.history_height;
            app.scroll_up(h.saturating_sub(2));
            return;
        }
        (KeyCode::PageDown, _) => {
            let amount = app.history_height.saturating_sub(2);
            app.scroll_down(amount);
            if app.scroll_offset == 0 {
                app.active_pane = ActivePane::Input;
            }
            return;
        }
        _ => {}
    }

    // Input pane keybindings
    if app.active_pane == ActivePane::Input {
        match (key.code, key.modifiers) {
            // Enter: submit input
            (KeyCode::Enter, KeyModifiers::NONE) => {
                let text = textarea.lines().join("\n").trim().to_string();
                if text.is_empty() {
                    return;
                }

                // Check for slash command
                if let Some(cmd) = SlashCommand::parse(&text) {
                    handle_slash_command(app, cmd);
                    *textarea = make_textarea();
                    return;
                }

                // Submit as user message
                if app.agent_running {
                    // Interrupt with new message
                    app.set_status(format!("Queued: {}", &text[..text.len().min(40)]));
                } else if let Some(tx) = to_agent {
                    app.add_user_message(text.clone());
                    app.agent_running = true;
                    app.loop_iteration = 0;

                    let msg = ToAgent::UserInput {
                        session_id: app.session_id.clone(),
                        message: text,
                        model: app.model.clone(),
                        max_iterations: 50,
                    };
                    if tx.try_send(msg).is_err() {
                        app.add_system_message("Failed to send message to agent".into());
                        app.agent_running = false;
                    }
                } else {
                    app.add_system_message("No agent subprocess connected".into());
                }

                *textarea = make_textarea();
                return;
            }
            // Alt+Enter or Ctrl+J: newline
            (KeyCode::Enter, KeyModifiers::ALT) | (KeyCode::Char('j'), KeyModifiers::CONTROL) => {
                textarea.insert_newline();
                return;
            }
            _ => {}
        }

        // Forward to textarea
        textarea.input(Input::from(key));
    }
}

fn handle_clarify_key(
    app: &mut App,
    to_agent: &Option<mpsc::Sender<ToAgent>>,
    key: KeyEvent,
) {
    match (key.code, key.modifiers) {
        // Submit response
        (KeyCode::Enter, KeyModifiers::NONE) => {
            let response = app.focused_pane().clarify_dialog.as_ref().unwrap().response();
            let question = app.focused_pane().clarify_dialog.as_ref().unwrap().question.clone();

            // Show what happened in the conversation
            app.add_system_message(format!("Agent asked: {question}"));
            if !response.is_empty() {
                app.add_system_message(format!("You answered: {response}"));
            }

            // Send response back to agent
            if let Some(tx) = to_agent {
                let _ = tx.try_send(ToAgent::ClarifyResponse {
                    response: response.clone(),
                });
            }

            // Dismiss dialog
            app.focused_pane_mut().clarify_dialog = None;
        }
        // Dismiss without answering (Esc)
        (KeyCode::Esc, _) => {
            let question = app.focused_pane().clarify_dialog.as_ref().unwrap().question.clone();
            app.add_system_message(format!("Agent asked: {question}"));
            app.add_system_message("(dismissed without answering)".into());

            // Send empty response so the agent doesn't block forever
            if let Some(tx) = to_agent {
                let _ = tx.try_send(ToAgent::ClarifyResponse {
                    response: String::new(),
                });
            }
            app.focused_pane_mut().clarify_dialog = None;
        }
        // Arrow keys for choice selection
        (KeyCode::Up, _) => {
            if let Some(ref mut dialog) = app.focused_pane_mut().clarify_dialog {
                dialog.select_up();
            }
        }
        (KeyCode::Down, _) => {
            if let Some(ref mut dialog) = app.focused_pane_mut().clarify_dialog {
                dialog.select_down();
            }
        }
        // Text editing
        (KeyCode::Backspace, _) => {
            if let Some(ref mut dialog) = app.focused_pane_mut().clarify_dialog {
                dialog.delete_back();
            }
        }
        (KeyCode::Delete, _) => {
            if let Some(ref mut dialog) = app.focused_pane_mut().clarify_dialog {
                dialog.delete_forward();
            }
        }
        (KeyCode::Left, _) => {
            if let Some(ref mut dialog) = app.focused_pane_mut().clarify_dialog {
                dialog.move_left();
            }
        }
        (KeyCode::Right, _) => {
            if let Some(ref mut dialog) = app.focused_pane_mut().clarify_dialog {
                dialog.move_right();
            }
        }
        (KeyCode::Home, _) => {
            if let Some(ref mut dialog) = app.focused_pane_mut().clarify_dialog {
                dialog.move_home();
            }
        }
        (KeyCode::End, _) => {
            if let Some(ref mut dialog) = app.focused_pane_mut().clarify_dialog {
                dialog.move_end();
            }
        }
        (KeyCode::Char(c), KeyModifiers::NONE | KeyModifiers::SHIFT) => {
            if let Some(ref mut dialog) = app.focused_pane_mut().clarify_dialog {
                dialog.insert_char(c);
            }
        }
        _ => {}
    }
}

fn handle_slash_command(app: &mut App, cmd: SlashCommand) {
    match cmd {
        SlashCommand::Help => {
            let help = [
                "/help     — Show this help",
                "/clear    — Clear conversation",
                "/new      — Start fresh conversation",
                "/model    — Switch model",
                "/verbose  — Cycle tool display",
                "/thinkon  — Show thinking blocks",
                "/thinkoff — Hide thinking blocks",
                "/usage    — Show token usage",
                "/context  — Show context window",
                "/quit     — Exit",
            ];
            app.add_system_message(help.join("\n"));
        }
        SlashCommand::Clear | SlashCommand::New => {
            app.messages.clear();
            app.input_tokens = 0;
            app.output_tokens = 0;
            app.scroll_to_bottom();
            app.set_status("Conversation cleared".into());
        }
        SlashCommand::ThinkOn => {
            app.show_thinking = true;
            app.set_status("Think blocks: visible".into());
        }
        SlashCommand::ThinkOff => {
            app.show_thinking = false;
            app.set_status("Think blocks: hidden".into());
        }
        SlashCommand::Usage => {
            let msg = format!(
                "Input: {} tokens\nOutput: {} tokens\nTotal: {} tokens",
                app.input_tokens,
                app.output_tokens,
                app.total_tokens()
            );
            app.add_system_message(msg);
        }
        SlashCommand::Context => {
            let pct = app.context_percent();
            let used = app.input_tokens;
            let cap = app.context_length;
            let remaining = cap.saturating_sub(used);
            let bar_len = 40;
            let filled = ((pct / 100.0) * bar_len as f32) as usize;
            let bar: String = "▓".repeat(filled) + &"░".repeat(bar_len - filled);
            let msg = format!(
                "Context Window\n[{bar}] {pct:.0}%\nUsed: {used} · Remaining: {remaining} · Capacity: {cap}"
            );
            app.add_system_message(msg);
        }
        SlashCommand::Quit => {
            app.running = false;
        }
        SlashCommand::Model(name) => {
            if name.is_empty() {
                let model_name = app.model.clone();
                app.add_system_message(format!("Current model: {}", model_name));
            } else {
                app.model = name.clone();
                app.set_status(format!("Model: {name}"));
            }
        }
        SlashCommand::Unknown(name) => {
            app.set_status(format!("Unknown command: /{name}"));
        }
        _ => {
            app.set_status("Command not yet implemented".into());
        }
    }
}

fn handle_agent_message(app: &mut App, msg: FromAgent) {
    match msg {
        FromAgent::Token { content, is_thinking } => {
            // Auto-start assistant message if this is the first token of a new response
            if app.streaming_text.is_empty()
                && !app
                    .messages
                    .last()
                    .map_or(false, |m| m.role == Role::Assistant && m.parts.is_empty())
            {
                app.begin_assistant_message();
            }
            app.append_token(&content, is_thinking);
        }
        FromAgent::ToolCallStart {
            tool_id,
            tool_name,
            args_preview,
        } => {
            // Auto-start assistant message if needed
            if !app
                .messages
                .last()
                .map_or(false, |m| m.role == Role::Assistant)
            {
                app.begin_assistant_message();
            }
            app.add_tool_call(tool_id, tool_name, args_preview);
        }
        FromAgent::ToolCallResult {
            tool_id,
            success,
            output,
            duration_ms,
        } => {
            app.complete_tool_call(&tool_id, success, output, duration_ms);
        }
        FromAgent::ResponseComplete {
            input_tokens,
            output_tokens,
            ..
        } => {
            app.finalize_response(input_tokens, output_tokens);
        }
        FromAgent::LoopStateChange {
            state, iteration, ..
        } => {
            app.loop_state = state;
            app.loop_iteration = iteration;
        }
        FromAgent::Done { reason, .. } => {
            app.agent_running = false;
            app.set_status(reason);
        }
        FromAgent::Error { message, .. } => {
            app.add_system_message(format!("Error: {message}"));
            app.agent_running = false;
        }
        FromAgent::SessionInfo {
            session_id,
            model,
            context_length,
        } => {
            app.session_id = session_id;
            app.model = model;
            if context_length > 0 {
                app.context_length = context_length;
            }
        }
        FromAgent::ClarifyRequest { question, choices, .. } => {
            app.focused_pane_mut().clarify_dialog =
                Some(app::ClarifyDialog::new(question, choices));
        }
        FromAgent::ContextCompressed {
            old_tokens,
            new_tokens,
        } => {
            app.set_status(format!(
                "Context compressed: {old_tokens} → {new_tokens} tokens"
            ));
            app.input_tokens = new_tokens;
        }
        FromAgent::Ready => {
            app.set_status("Agent ready".into());
        }

        // ── Skills ────────────────────────────────────────────────────
        FromAgent::SkillStart {
            skill_name,
            display_name,
            scope: _,
            args,
        } => {
            let label = if display_name.is_empty() {
                skill_name
            } else {
                display_name
            };
            let detail = if args.is_empty() {
                String::new()
            } else {
                format!(" {args}")
            };
            app.add_system_message(format!("▶ {label}{detail}"));
        }
        FromAgent::SkillProgress {
            skill_name: _,
            step,
            step_number,
            total_steps,
            agent: _,
        } => {
            let prefix = if total_steps > 0 {
                format!("  ③ {step_number}/{total_steps}")
            } else {
                format!("  ③ {step_number}")
            };
            app.set_status(format!("{prefix} {step}"));
        }
        FromAgent::SkillComplete {
            skill_name: _,
            success,
            summary,
            duration_ms,
        } => {
            let icon = if success { "✓" } else { "✗" };
            let dur = duration_ms as f32 / 1000.0;
            app.add_system_message(format!("{icon} {summary} ({dur:.1}s)"));
        }

        // ── Shared Memory ─────────────────────────────────────────────
        FromAgent::MemoryOp { op, file, preview } => {
            let icon = match op.as_str() {
                "write" | "append" => "📝",
                "read" => "📖",
                _ => "💾",
            };
            let detail = if preview.is_empty() {
                String::new()
            } else {
                format!(" — {}", &preview[..preview.len().min(60)])
            };
            app.set_status(format!("{icon} memory:{op} {file}{detail}"));
        }

        // ── Multi-Agent (future) ──────────────────────────────────────
        FromAgent::PeerQuery { target_agent, question, .. } => {
            app.add_system_message(format!("→ @{target_agent}: {question}"));
        }
        FromAgent::DelegateTask { target_agent, task, .. } => {
            app.add_system_message(format!("→ delegating to @{target_agent}: {task}"));
        }
        FromAgent::DelegationResult { result, success, .. } => {
            let icon = if success { "✓" } else { "✗" };
            app.add_system_message(format!("{icon} delegation result: {result}"));
        }
    }
}

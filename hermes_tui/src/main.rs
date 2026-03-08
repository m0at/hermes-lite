#![allow(dead_code)]

mod app;
mod colors;
mod mention;
mod multi;
mod protocol;
mod subprocess;
mod ui;

use std::collections::HashMap;
use std::io;

use crossterm::{
    event::{self, Event, KeyCode, KeyEvent, KeyModifiers, MouseEvent, MouseEventKind, EnableMouseCapture, DisableMouseCapture},
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
    ExecutableCommand,
};
use ratatui::prelude::*;
use tokio::sync::mpsc;
use tui_textarea::{Input, TextArea};

use app::{ActivePane, App, LayoutMode, MessagePart, Role, SlashCommand};
use mention::MentionTarget;
use protocol::{FromAgent, ToAgent};

// ── Per-pane I/O ────────────────────────────────────────────────────────

struct PaneIO {
    to_agent: mpsc::Sender<ToAgent>,
}

fn make_textarea<'a>() -> TextArea<'a> {
    let mut ta = TextArea::default();
    ta.set_cursor_line_style(Style::default());
    ta.set_cursor_style(Style::default().fg(colors::CREAM).reversed());
    ta.set_placeholder_text("Type a message...");
    ta.set_placeholder_style(Style::default().fg(colors::DIM).italic());
    ta
}

/// Spawn an agent subprocess and return (PaneIO, Receiver<FromAgent>).
async fn spawn_agent() -> Result<(PaneIO, mpsc::Receiver<FromAgent>), String> {
    let (agent, from_rx) = subprocess::AgentProcess::spawn(
        mpsc::channel::<FromAgent>(1).0,
    )
    .await?;

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

    Ok((PaneIO { to_agent: tx }, from_rx))
}

#[tokio::main]
async fn main() -> io::Result<()> {
    // Terminal setup
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    stdout.execute(EnterAlternateScreen)?;
    stdout.execute(EnableMouseCapture)?;
    let mut terminal = Terminal::new(CrosstermBackend::new(stdout))?;

    let mut app = App::new();
    let mut textareas: Vec<TextArea> = vec![make_textarea()];

    // Per-pane I/O and receivers
    let mut pane_ios: Vec<Option<PaneIO>> = Vec::new();
    let mut pane_rxs: Vec<Option<mpsc::Receiver<FromAgent>>> = Vec::new();

    // Spawn initial agent subprocess for pane 0
    match spawn_agent().await {
        Ok((pio, rx)) => {
            app.set_status("Agent subprocess started".into());
            pane_ios.push(Some(pio));
            pane_rxs.push(Some(rx));
        }
        Err(e) => {
            app.add_system_message(format!("Failed to start agent: {e}"));
            app.set_status("No agent — type /quit to exit".into());
            pane_ios.push(None);
            pane_rxs.push(None);
        }
    };

    // Channel for async subprocess spawn results
    let (spawn_tx, mut spawn_rx) = mpsc::channel::<(u8, Result<(PaneIO, mpsc::Receiver<FromAgent>), String>)>(4);

    // Pending pull-back requests: target_pane_id -> source_pane_id
    let mut pending_pullbacks: HashMap<u8, u8> = HashMap::new();

    // Pending delegation requests: request_id -> source_pane_id
    let mut pending_delegations: HashMap<String, u8> = HashMap::new();

    // Event loop
    while app.running {
        // Check for completed spawns
        while let Ok((pane_id, result)) = spawn_rx.try_recv() {
            let idx = pane_id as usize;
            match result {
                Ok((pio, rx)) => {
                    if idx < pane_ios.len() {
                        pane_ios[idx] = Some(pio);
                        pane_rxs[idx] = Some(rx);
                    }
                    if idx < app.panes.len() {
                        app.panes[idx].set_status("Agent subprocess started".into());
                    }
                }
                Err(e) => {
                    if idx < app.panes.len() {
                        app.panes[idx].add_system_message(format!("Failed to start agent: {e}"));
                    }
                }
            }
        }

        // Render
        terminal.draw(|frame| {
            if app.pane_count() <= 1 {
                // Single-pane: use ui.rs (backward compatible)
                let area = frame.area();
                let input_lines = textareas.first().map_or(1, |ta| ta.lines().len().max(1));
                let layout = ui::build_layout(area, input_lines);

                ui::render_history(&mut app, frame, layout.history);
                ui::render_separator(frame, layout.separator1);
                ui::render_spinner(&app, frame, layout.spinner);
                ui::render_separator(frame, layout.separator2);
                ui::render_input_area(&app, frame, layout.input, &textareas[0]);
                ui::render_status_bar(&app, frame, layout.status_bar);

                // Clarify dialog overlay
                if let Some(ref dialog) = app.focused_pane().clarify_dialog {
                    ui::render_clarify_dialog(dialog, frame, area);
                }
                // Help overlay
                if app.show_help {
                    ui::render_help_overlay(frame, area);
                }
            } else {
                // Multi-pane: use multi.rs
                match app.layout_mode {
                    LayoutMode::Split { .. } => multi::render_split(frame, &mut app, &textareas),
                    LayoutMode::Tabs => multi::render_tabs(frame, &mut app, &textareas),
                }

                // Overlays (on top of everything)
                let area = frame.area();
                if let Some(ref dialog) = app.focused_pane().clarify_dialog {
                    ui::render_clarify_dialog(dialog, frame, area);
                }
                if app.show_help {
                    ui::render_help_overlay(frame, area);
                }
            }
        })?;

        // Tick spinner for all running panes
        for pane in &mut app.panes {
            if pane.agent_running {
                pane.tick_spinner();
            }
        }

        // Poll terminal events (50ms tick for spinner animation)
        if event::poll(std::time::Duration::from_millis(50))? {
            match event::read()? {
                Event::Key(key) => handle_key_event(
                    &mut app,
                    &mut textareas,
                    &mut pane_ios,
                    &mut pane_rxs,
                    &spawn_tx,
                    &mut pending_pullbacks,
                    key,
                ),
                Event::Mouse(mouse) => handle_mouse_event(&mut app, mouse),
                Event::Resize(_, _) => {}
                _ => {}
            }
        }

        // Poll agent messages from ALL panes
        for pane_idx in 0..pane_rxs.len() {
            let rx = match pane_rxs.get_mut(pane_idx) {
                Some(Some(rx)) => rx,
                _ => continue,
            };

            loop {
                match rx.try_recv() {
                    Ok(msg) => {
                        handle_agent_message_for_pane(
                            &mut app,
                            pane_idx,
                            msg,
                            &pane_ios,
                            &mut pending_pullbacks,
                            &mut pending_delegations,
                        );
                        // Mark unread if not focused
                        if pane_idx != app.focused as usize {
                            if pane_idx < app.panes.len() {
                                app.panes[pane_idx].unread = true;
                            }
                        }
                    }
                    Err(mpsc::error::TryRecvError::Empty) => break,
                    Err(mpsc::error::TryRecvError::Disconnected) => {
                        if pane_idx < app.panes.len() {
                            app.panes[pane_idx].agent_running = false;
                            app.panes[pane_idx].add_system_message(
                                "Agent process disconnected — respawning...".into(),
                            );
                        }
                        pane_rxs[pane_idx] = None;
                        // Auto-respawn the subprocess
                        let tx = spawn_tx.clone();
                        let pid = pane_idx as u8;
                        tokio::spawn(async move {
                            let result = spawn_agent().await;
                            let _ = tx.send((pid, result)).await;
                        });
                        break;
                    }
                }
            }
        }
    }

    // Shutdown: notify all agent subprocesses
    for pio in pane_ios.iter().flatten() {
        let _ = pio.to_agent.try_send(ToAgent::Shutdown);
    }

    // Teardown terminal
    disable_raw_mode()?;
    io::stdout().execute(DisableMouseCapture)?;
    io::stdout().execute(LeaveAlternateScreen)?;
    Ok(())
}

// ── Mouse event handling ────────────────────────────────────────────────

fn handle_mouse_event(app: &mut App, mouse: MouseEvent) {
    match mouse.kind {
        MouseEventKind::ScrollUp => {
            app.active_pane = ActivePane::History;
            app.scroll_up(3);
        }
        MouseEventKind::ScrollDown => {
            app.scroll_down(3);
            if app.scroll_offset == 0 {
                app.active_pane = ActivePane::Input;
            }
        }
        _ => {}
    }
}

// ── Key event handling ──────────────────────────────────────────────────

fn handle_key_event(
    app: &mut App,
    textareas: &mut Vec<TextArea>,
    pane_ios: &mut Vec<Option<PaneIO>>,
    pane_rxs: &mut Vec<Option<mpsc::Receiver<FromAgent>>>,
    spawn_tx: &mpsc::Sender<(u8, Result<(PaneIO, mpsc::Receiver<FromAgent>), String>)>,
    pending_pullbacks: &mut HashMap<u8, u8>,
    key: KeyEvent,
) {
    // Help overlay captures Esc
    if app.show_help {
        if matches!(key.code, KeyCode::Esc | KeyCode::Char('q')) {
            app.show_help = false;
        }
        // Any other key also dismisses
        else {
            app.show_help = false;
        }
        return;
    }

    // Clarify dialog captures all input when active
    if app.focused_pane().clarify_dialog.is_some() {
        handle_clarify_key(app, pane_ios, key);
        return;
    }

    // Global keybindings
    match (key.code, key.modifiers) {
        // Ctrl+C: interrupt or exit
        (KeyCode::Char('c'), KeyModifiers::CONTROL) => {
            let focused = app.focused as usize;
            if app.panes[focused].agent_running {
                if let Some(Some(ref pio)) = pane_ios.get(focused) {
                    let _ = pio.to_agent.try_send(ToAgent::Interrupt);
                }
                app.panes[focused].set_status("Interrupting agent...".into());
                app.panes[focused].agent_running = false;
            } else {
                let text = textareas[focused].lines().join("\n");
                if text.is_empty() {
                    app.running = false;
                } else {
                    textareas[focused] = make_textarea();
                }
            }
            return;
        }
        // Ctrl+D: exit
        (KeyCode::Char('d'), KeyModifiers::CONTROL) => {
            app.running = false;
            return;
        }
        // Ctrl+Left: previous pane
        (KeyCode::Left, KeyModifiers::CONTROL) => {
            app.prev_pane();
            return;
        }
        // Ctrl+Right: next pane
        (KeyCode::Right, KeyModifiers::CONTROL) => {
            app.next_pane();
            return;
        }
        // Alt+1-9: focus pane by index
        (KeyCode::Char(c @ '1'..='9'), KeyModifiers::ALT) => {
            let idx = (c as u8 - b'1') as usize;
            if idx < app.pane_count() {
                app.focused = idx as u8;
                app.panes[idx].unread = false;
            }
            return;
        }
        // Page Up/Down: scroll history (page at a time)
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
        // Shift+Up/Down: scroll history line by line
        (KeyCode::Up, KeyModifiers::SHIFT) => {
            app.active_pane = ActivePane::History;
            app.scroll_up(1);
            return;
        }
        (KeyCode::Down, KeyModifiers::SHIFT) => {
            app.scroll_down(1);
            if app.scroll_offset == 0 {
                app.active_pane = ActivePane::Input;
            }
            return;
        }
        // Home: scroll to top, End: scroll to bottom
        (KeyCode::Home, _) if app.active_pane == ActivePane::History => {
            app.scroll_up(u16::MAX / 2);
            return;
        }
        (KeyCode::End, _) if app.active_pane == ActivePane::History => {
            app.scroll_offset = 0;
            app.active_pane = ActivePane::Input;
            return;
        }
        // Escape returns focus to input
        (KeyCode::Esc, _) if app.active_pane == ActivePane::History => {
            app.scroll_offset = 0;
            app.active_pane = ActivePane::Input;
            return;
        }
        _ => {}
    }

    // Input pane keybindings
    let focused = app.focused as usize;
    if app.active_pane == ActivePane::Input {
        match (key.code, key.modifiers) {
            // Enter: submit input
            (KeyCode::Enter, KeyModifiers::NONE) => {
                let text = textareas[focused].lines().join("\n").trim().to_string();
                if text.is_empty() {
                    return;
                }

                // Check for slash command
                if let Some(cmd) = SlashCommand::parse(&text) {
                    let action = handle_slash_command(app, cmd, pane_ios, pane_rxs, textareas, spawn_tx, pending_pullbacks);
                    textareas[focused] = make_textarea();

                    if let SlashAction::CloseFocused = action {
                        let closing = focused;
                        // Send shutdown
                        if let Some(Some(ref pio)) = pane_ios.get(closing) {
                            let _ = pio.to_agent.try_send(ToAgent::Shutdown);
                        }
                        if app.close_pane(closing as u8) {
                            if closing < pane_ios.len() { pane_ios.remove(closing); }
                            if closing < pane_rxs.len() { pane_rxs.remove(closing); }
                            if closing < textareas.len() { textareas.remove(closing); }
                            app.set_status(format!("Closed pane {}", closing + 1));
                            if app.pane_count() == 1 {
                                app.layout_mode = LayoutMode::Tabs;
                            }
                        }
                    }
                    return;
                }

                // Check for @mention
                let parsed = mention::parse_input(&text);
                if let Some(ref target) = parsed.mention {
                    handle_mention(app, target, &parsed.message, pane_ios, pending_pullbacks);
                    textareas[focused] = make_textarea();
                    return;
                }

                // Submit as user message to focused pane
                submit_to_pane(app, focused, &text, pane_ios);
                textareas[focused] = make_textarea();
                return;
            }
            // Alt+Enter or Ctrl+J: newline
            (KeyCode::Enter, KeyModifiers::ALT) | (KeyCode::Char('j'), KeyModifiers::CONTROL) => {
                textareas[focused].insert_newline();
                return;
            }
            _ => {}
        }

        // Forward to textarea
        textareas[focused].input(Input::from(key));
    }
}

fn submit_to_pane(app: &mut App, pane_idx: usize, text: &str, pane_ios: &[Option<PaneIO>]) {
    if pane_idx >= app.panes.len() {
        return;
    }

    if app.panes[pane_idx].agent_running {
        app.panes[pane_idx].set_status(format!("Queued: {}", &text[..text.len().min(40)]));
        return;
    }

    if let Some(Some(ref pio)) = pane_ios.get(pane_idx) {
        app.panes[pane_idx].add_user_message(text.to_string());
        app.panes[pane_idx].agent_running = true;
        app.panes[pane_idx].loop_iteration = 0;

        let msg = ToAgent::UserInput {
            session_id: app.panes[pane_idx].session_id.clone(),
            message: text.to_string(),
            model: app.panes[pane_idx].model.clone(),
            max_iterations: 200,
        };
        if pio.to_agent.try_send(msg).is_err() {
            app.panes[pane_idx].add_system_message("Failed to send message to agent".into());
            app.panes[pane_idx].agent_running = false;
        }
    } else {
        app.panes[pane_idx].add_system_message("No agent subprocess connected".into());
    }
}

fn handle_mention(
    app: &mut App,
    target: &MentionTarget,
    message: &str,
    pane_ios: &[Option<PaneIO>],
    pending_pullbacks: &mut HashMap<u8, u8>,
) {
    match target {
        MentionTarget::Agent { name, pull_back } => {
            if let Some(target_id) = app.pane_by_name(name) {
                let target_idx = target_id as usize;
                if *pull_back {
                    pending_pullbacks.insert(target_id, app.focused);
                }
                submit_to_pane(app, target_idx, message, pane_ios);
                let source_name = app.panes[app.focused as usize].name.clone();
                app.panes[app.focused as usize].add_system_message(
                    format!("→ @{name}: {}", &message[..message.len().min(60)]),
                );
                // Mark source context on target
                app.panes[target_idx].add_system_message(
                    format!("(from @{source_name})"),
                );
            } else {
                app.focused_pane_mut().add_system_message(format!("No agent named '{name}'"));
            }
        }
        MentionTarget::All => {
            // Broadcast to all panes
            for i in 0..app.panes.len() {
                submit_to_pane(app, i, message, pane_ios);
            }
        }
    }
}

fn handle_clarify_key(
    app: &mut App,
    pane_ios: &[Option<PaneIO>],
    key: KeyEvent,
) {
    let focused = app.focused as usize;
    let to_agent = pane_ios.get(focused).and_then(|p| p.as_ref());

    match (key.code, key.modifiers) {
        (KeyCode::Enter, KeyModifiers::NONE) => {
            let response = app.focused_pane().clarify_dialog.as_ref().unwrap().response();
            let question = app.focused_pane().clarify_dialog.as_ref().unwrap().question.clone();

            app.panes[focused].add_system_message(format!("Agent asked: {question}"));
            if !response.is_empty() {
                app.panes[focused].add_system_message(format!("You answered: {response}"));
            }

            if let Some(pio) = to_agent {
                let _ = pio.to_agent.try_send(ToAgent::ClarifyResponse {
                    response: response.clone(),
                });
            }

            app.focused_pane_mut().clarify_dialog = None;
        }
        (KeyCode::Esc, _) => {
            let question = app.focused_pane().clarify_dialog.as_ref().unwrap().question.clone();
            app.panes[focused].add_system_message(format!("Agent asked: {question}"));
            app.panes[focused].add_system_message("(dismissed without answering)".into());

            if let Some(pio) = to_agent {
                let _ = pio.to_agent.try_send(ToAgent::ClarifyResponse {
                    response: String::new(),
                });
            }
            app.focused_pane_mut().clarify_dialog = None;
        }
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

// ── Slash commands ──────────────────────────────────────────────────────

/// Action returned by slash commands that needs handling at the top level.
enum SlashAction {
    None,
    CloseFocused,
}

fn handle_slash_command(
    app: &mut App,
    cmd: SlashCommand,
    pane_ios: &mut Vec<Option<PaneIO>>,
    pane_rxs: &mut Vec<Option<mpsc::Receiver<FromAgent>>>,
    textareas: &mut Vec<TextArea>,
    spawn_tx: &mpsc::Sender<(u8, Result<(PaneIO, mpsc::Receiver<FromAgent>), String>)>,
    pending_pullbacks: &mut HashMap<u8, u8>,
) -> SlashAction {
    match cmd {
        SlashCommand::Help => {
            app.show_help = !app.show_help;
        }
        SlashCommand::Clear | SlashCommand::New => {
            let focused = app.focused as usize;
            app.panes[focused].messages.clear();
            app.panes[focused].input_tokens = 0;
            app.panes[focused].output_tokens = 0;
            app.panes[focused].scroll_to_bottom();
            app.panes[focused].set_status("Conversation cleared".into());
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
            let focused = app.focused as usize;
            let pane = &app.panes[focused];
            let msg = format!(
                "Input: {} tokens\nOutput: {} tokens\nTotal: {} tokens",
                pane.input_tokens,
                pane.output_tokens,
                pane.total_tokens()
            );
            app.panes[focused].add_system_message(msg);
        }
        SlashCommand::Context => {
            let focused = app.focused as usize;
            let pane = &app.panes[focused];
            let pct = pane.context_percent();
            let used = pane.input_tokens;
            let cap = pane.context_length;
            let remaining = cap.saturating_sub(used);
            let bar_len = 40;
            let filled = ((pct / 100.0) * bar_len as f32) as usize;
            let bar: String = "▓".repeat(filled) + &"░".repeat(bar_len - filled);
            let msg = format!(
                "Context Window\n[{bar}] {pct:.0}%\nUsed: {used} · Remaining: {remaining} · Capacity: {cap}"
            );
            app.panes[focused].add_system_message(msg);
        }
        SlashCommand::Quit => {
            app.running = false;
        }
        SlashCommand::Model(name) => {
            let focused = app.focused as usize;
            if name.is_empty() {
                let model_name = app.panes[focused].model.clone();
                app.panes[focused].add_system_message(format!("Current model: {}", model_name));
            } else {
                app.panes[focused].model = name.clone();
                app.panes[focused].set_status(format!("Model: {name}"));
            }
        }

        // ── Multi-agent commands ────────────────────────────────────────

        SlashCommand::Split => {
            spawn_new_pane(app, textareas, pane_ios, pane_rxs, spawn_tx, LayoutMode::Split { direction: Direction::Horizontal });
        }
        SlashCommand::HSplit => {
            spawn_new_pane(app, textareas, pane_ios, pane_rxs, spawn_tx, LayoutMode::Split { direction: Direction::Vertical });
        }
        SlashCommand::Tabs => {
            app.layout_mode = LayoutMode::Tabs;
            app.set_status("Layout: tabs".into());
        }
        SlashCommand::Close => {
            if app.pane_count() <= 1 {
                app.set_status("Can't close the last pane".into());
            } else {
                return SlashAction::CloseFocused;
            }
        }
        SlashCommand::Name(name) => {
            if name.is_empty() {
                let current = app.focused_pane().name.clone();
                app.set_status(format!("Current name: {current}"));
            } else {
                app.focused_pane_mut().name = name.clone();
                app.set_status(format!("Renamed to: {name}"));
            }
        }
        SlashCommand::Focus(target) => {
            // Try as index first (1-based)
            if let Ok(n) = target.parse::<usize>() {
                let idx = n.saturating_sub(1);
                if idx < app.pane_count() {
                    app.focused = idx as u8;
                    app.panes[idx].unread = false;
                    let name = app.panes[idx].name.clone();
                    app.set_status(format!("Focused: {name}"));
                } else {
                    app.set_status(format!("No pane #{n}"));
                }
            } else if let Some(id) = app.pane_by_name(&target) {
                app.focused = id;
                app.panes[id as usize].unread = false;
                app.set_status(format!("Focused: {target}"));
            } else {
                app.set_status(format!("No pane named '{target}'"));
            }
        }
        SlashCommand::Broadcast(message) => {
            if message.is_empty() {
                app.broadcast_mode = !app.broadcast_mode;
                let state = if app.broadcast_mode { "ON" } else { "OFF" };
                app.set_status(format!("Broadcast mode: {state}"));
            } else {
                for i in 0..app.panes.len() {
                    submit_to_pane(app, i, &message, pane_ios);
                }
            }
        }
        SlashCommand::Ask { target, message } => {
            if let Some(target_id) = app.pane_by_name(&target) {
                pending_pullbacks.insert(target_id, app.focused);
                submit_to_pane(app, target_id as usize, &message, pane_ios);
                app.set_status(format!("Asked @{target}, will pull response back"));
            } else {
                // Try as index
                if let Ok(n) = target.parse::<usize>() {
                    let idx = n.saturating_sub(1);
                    if idx < app.pane_count() {
                        pending_pullbacks.insert(idx as u8, app.focused);
                        submit_to_pane(app, idx, &message, pane_ios);
                        app.set_status(format!("Asked pane #{n}, will pull response back"));
                    } else {
                        app.set_status(format!("No pane #{n}"));
                    }
                } else {
                    app.set_status(format!("No pane named '{target}'"));
                }
            }
        }
        SlashCommand::ListAgents => {
            let mut lines = Vec::new();
            for (i, pane) in app.panes.iter().enumerate() {
                let focus = if i == app.focused as usize { " (focused)" } else { "" };
                let status = if pane.agent_running { "running" } else { "idle" };
                let model = if pane.model.is_empty() { "no model" } else { &pane.model };
                let tokens = pane.total_tokens();
                lines.push(format!(
                    "  {} [{}] {}{} — {} ({} tokens)",
                    i + 1, status, pane.name, focus, model, tokens
                ));
            }
            app.add_system_message(format!("Agents:\n{}", lines.join("\n")));
        }
        SlashCommand::Zoom => {
            // Toggle between tabs (zoomed) and split
            match app.layout_mode {
                LayoutMode::Tabs => {
                    app.layout_mode = LayoutMode::Split { direction: Direction::Horizontal };
                    app.set_status("Layout: split".into());
                }
                LayoutMode::Split { .. } => {
                    app.layout_mode = LayoutMode::Tabs;
                    app.set_status("Layout: tabs (zoomed)".into());
                }
            }
        }

        SlashCommand::Unknown(name) => {
            app.set_status(format!("Unknown command: /{name}"));
        }
        _ => {
            app.set_status("Command not yet implemented".into());
        }
    }
    SlashAction::None
}

fn spawn_new_pane(
    app: &mut App,
    textareas: &mut Vec<TextArea>,
    pane_ios: &mut Vec<Option<PaneIO>>,
    pane_rxs: &mut Vec<Option<mpsc::Receiver<FromAgent>>>,
    spawn_tx: &mpsc::Sender<(u8, Result<(PaneIO, mpsc::Receiver<FromAgent>), String>)>,
    layout: LayoutMode,
) {
    let new_id = app.spawn_pane();
    app.layout_mode = layout;
    textareas.push(make_textarea());
    pane_ios.push(None);   // placeholder until spawn completes
    pane_rxs.push(None);

    app.panes[new_id as usize].set_status("Starting agent subprocess...".into());

    // Spawn subprocess asynchronously
    let tx = spawn_tx.clone();
    tokio::spawn(async move {
        let result = spawn_agent().await;
        let _ = tx.send((new_id, result)).await;
    });

    let pane_name = app.panes[new_id as usize].name.clone();
    app.set_status(format!("Spawned pane {} ({pane_name})", new_id + 1));
}

// ── Agent message handling ──────────────────────────────────────────────

fn handle_agent_message_for_pane(
    app: &mut App,
    pane_idx: usize,
    msg: FromAgent,
    pane_ios: &[Option<PaneIO>],
    pending_pullbacks: &mut HashMap<u8, u8>,
    pending_delegations: &mut HashMap<String, u8>,
) {
    if pane_idx >= app.panes.len() {
        return;
    }

    // Use app.panes[pane_idx] directly in each arm to avoid holding a long-lived
    // mutable borrow that conflicts with app.pane_by_name() in multi-agent arms.
    match msg {
        FromAgent::Token { content, is_thinking } => {
            let pane = &mut app.panes[pane_idx];
            if pane.streaming_text.is_empty()
                && !pane
                    .messages
                    .last()
                    .map_or(false, |m| m.role == Role::Assistant && m.parts.is_empty())
            {
                pane.begin_assistant_message();
            }
            pane.append_token(&content, is_thinking);
        }
        FromAgent::ToolCallStart {
            tool_id,
            tool_name,
            args_preview,
        } => {
            let pane = &mut app.panes[pane_idx];
            if !pane
                .messages
                .last()
                .map_or(false, |m| m.role == Role::Assistant)
            {
                pane.begin_assistant_message();
            }
            pane.add_tool_call(tool_id, tool_name, args_preview);
        }
        FromAgent::ToolCallResult {
            tool_id,
            success,
            output,
            duration_ms,
        } => {
            app.panes[pane_idx].complete_tool_call(&tool_id, success, output, duration_ms);
        }
        FromAgent::ResponseComplete {
            input_tokens,
            output_tokens,
            ..
        } => {
            app.panes[pane_idx].finalize_response(input_tokens, output_tokens);
        }
        FromAgent::LoopStateChange {
            state, iteration, ..
        } => {
            app.panes[pane_idx].loop_state = state;
            app.panes[pane_idx].loop_iteration = iteration;
        }
        FromAgent::Done { reason, iterations } => {
            app.panes[pane_idx].agent_running = false;

            // Auto-continue if agent hit max iterations (still had work to do)
            let is_max_iter = reason.contains("completed") && iterations >= 190;
            let is_truncated = reason.contains("truncat");
            if is_max_iter || is_truncated {
                let continue_msg = if is_max_iter {
                    "You hit the iteration limit. Continue where you left off — \
                     finish what you were doing."
                } else {
                    "Your response was truncated. Please continue."
                };
                app.panes[pane_idx].set_status(format!("Auto-continuing ({reason})..."));
                submit_to_pane(app, pane_idx, continue_msg, pane_ios);
            } else {
                app.panes[pane_idx].set_status(reason);
            }

            // Handle pull-back: copy the response to the requesting pane
            let pane_id = pane_idx as u8;
            if let Some(source_id) = pending_pullbacks.remove(&pane_id) {
                let source_idx = source_id as usize;
                let response_text = app.panes[pane_idx]
                    .messages
                    .iter()
                    .rev()
                    .find(|m| m.role == Role::Assistant)
                    .map(|m| {
                        m.parts
                            .iter()
                            .filter_map(|p| {
                                if let MessagePart::Text(t) = p {
                                    Some(t.as_str())
                                } else {
                                    None
                                }
                            })
                            .collect::<Vec<_>>()
                            .join("")
                    })
                    .unwrap_or_default();

                if !response_text.is_empty() && source_idx < app.panes.len() {
                    let target_name = app.panes[pane_idx].name.clone();
                    app.panes[source_idx].add_system_message(
                        format!("← @{target_name} responded:\n{response_text}"),
                    );
                }
            }
        }
        FromAgent::Error { message, .. } => {
            app.panes[pane_idx].add_system_message(format!("Error: {message}"));
            app.panes[pane_idx].agent_running = false;
        }
        FromAgent::SessionInfo {
            session_id,
            model,
            context_length,
        } => {
            app.panes[pane_idx].session_id = session_id;
            app.panes[pane_idx].model = model;
            if context_length > 0 {
                app.panes[pane_idx].context_length = context_length;
            }
        }
        FromAgent::ClarifyRequest { question, choices, .. } => {
            app.panes[pane_idx].clarify_dialog = Some(app::ClarifyDialog::new(question, choices));
        }
        FromAgent::ContextCompressed {
            old_tokens,
            new_tokens,
        } => {
            app.panes[pane_idx].set_status(format!(
                "Context compressed: {old_tokens} → {new_tokens} tokens"
            ));
            app.panes[pane_idx].input_tokens = new_tokens;
        }
        FromAgent::Ready => {
            app.panes[pane_idx].set_status("Agent ready".into());
        }

        // ── Skills ──────────────────────────────────────────────────────
        FromAgent::SkillStart {
            skill_name,
            display_name,
            args,
            ..
        } => {
            let label = if display_name.is_empty() { skill_name } else { display_name };
            let detail = if args.is_empty() { String::new() } else { format!(" {args}") };
            app.panes[pane_idx].add_system_message(format!("▶ {label}{detail}"));
        }
        FromAgent::SkillProgress {
            step,
            step_number,
            total_steps,
            ..
        } => {
            let prefix = if total_steps > 0 {
                format!("  ③ {step_number}/{total_steps}")
            } else {
                format!("  ③ {step_number}")
            };
            app.panes[pane_idx].set_status(format!("{prefix} {step}"));
        }
        FromAgent::SkillComplete {
            success,
            summary,
            duration_ms,
            ..
        } => {
            let icon = if success { "✓" } else { "✗" };
            let dur = duration_ms as f32 / 1000.0;
            app.panes[pane_idx].add_system_message(format!("{icon} {summary} ({dur:.1}s)"));
        }

        // ── Shared Memory ───────────────────────────────────────────────
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
            app.panes[pane_idx].set_status(format!("{icon} memory:{op} {file}{detail}"));
        }

        // ── Multi-Agent routing ─────────────────────────────────────────
        FromAgent::PeerQuery {
            target_agent,
            question,
            request_id: _,
        } => {
            if let Some(target_id) = app.pane_by_name(&target_agent) {
                let source_name = app.panes[pane_idx].name.clone();
                submit_to_pane(app, target_id as usize, &question, pane_ios);
                app.panes[pane_idx].add_system_message(
                    format!("→ queried @{target_agent}: {}", &question[..question.len().min(60)]),
                );
                app.panes[target_id as usize].add_system_message(
                    format!("(peer query from @{source_name})"),
                );
            } else {
                app.panes[pane_idx].add_system_message(
                    format!("→ @{target_agent}: {question} (agent not found)"),
                );
            }
        }
        FromAgent::DelegateTask {
            target_agent,
            task,
            context,
            request_id,
        } => {
            if let Some(target_id) = app.pane_by_name(&target_agent) {
                let source_name = app.panes[pane_idx].name.clone();
                pending_delegations.insert(request_id.clone(), pane_idx as u8);

                if let Some(Some(ref pio)) = pane_ios.get(target_id as usize) {
                    let _ = pio.to_agent.try_send(ToAgent::DelegatedTask {
                        from_agent: source_name.clone(),
                        request_id,
                        task: task.clone(),
                        context,
                    });
                    app.panes[target_id as usize].agent_running = true;
                }
                app.panes[pane_idx].add_system_message(
                    format!("→ delegated to @{target_agent}: {}", &task[..task.len().min(60)]),
                );
            } else {
                app.panes[pane_idx].add_system_message(
                    format!("→ @{target_agent}: {task} (agent not found)"),
                );
            }
        }
        FromAgent::DelegationResult {
            request_id,
            result,
            success,
        } => {
            let icon = if success { "✓" } else { "✗" };
            let from_name = app.panes[pane_idx].name.clone();
            if let Some(source_idx) = pending_delegations.remove(&request_id) {
                let sidx = source_idx as usize;
                if sidx < app.panes.len() {
                    app.panes[sidx].add_system_message(
                        format!("{icon} delegation result from @{from_name}: {result}"),
                    );
                    // Forward result to source agent subprocess so it can
                    // continue with the result in its conversation context.
                    if let Some(Some(ref pio)) = pane_ios.get(sidx) {
                        let _ = pio.to_agent.try_send(ToAgent::CrossAgentContext {
                            from_agent: from_name,
                            summary: format!("[{icon}] {result}"),
                            full_history: None,
                        });
                    }
                }
            } else {
                app.panes[pane_idx].add_system_message(
                    format!("{icon} delegation result: {result}"),
                );
            }
        }
    }
}

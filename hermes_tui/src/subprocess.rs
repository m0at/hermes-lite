use std::path::PathBuf;
use std::process::Stdio;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::mpsc;

use crate::protocol::{FromAgent, ToAgent};

pub struct AgentProcess {
    child: Child,
    tx: mpsc::Sender<String>,
}

impl AgentProcess {
    /// Spawn the Python agent in subprocess mode.
    /// Returns (AgentProcess, receiver for parsed messages).
    pub async fn spawn(
        _agent_rx: mpsc::Sender<FromAgent>,
    ) -> Result<(Self, mpsc::Receiver<FromAgent>), String> {
        let script = find_run_agent()?;

        let mut child = Command::new("python3")
            .arg(&script)
            .arg("--subprocess-mode")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .map_err(|e| format!("Failed to spawn agent: {e}"))?;

        let stdout = child.stdout.take().ok_or("No stdout")?;
        let stderr = child.stderr.take().ok_or("No stderr")?;
        let stdin = child.stdin.take().ok_or("No stdin")?;

        let (from_agent_tx, from_agent_rx) = mpsc::channel::<FromAgent>(256);

        // Reader task: parse JSON lines from agent stdout
        let reader_tx = from_agent_tx.clone();
        tokio::spawn(async move {
            let mut reader = BufReader::new(stdout).lines();
            while let Ok(Some(line)) = reader.next_line().await {
                if line.trim().is_empty() {
                    continue;
                }
                match serde_json::from_str::<FromAgent>(&line) {
                    Ok(msg) => {
                        if reader_tx.send(msg).await.is_err() {
                            break;
                        }
                    }
                    Err(e) => {
                        let _ = reader_tx
                            .send(FromAgent::Error {
                                message: format!("Parse error: {e}"),
                                code: "PARSE_ERROR".into(),
                            })
                            .await;
                    }
                }
            }
        });

        // Stderr logger: forward to FromAgent::Error for display
        let stderr_tx = from_agent_tx;
        tokio::spawn(async move {
            let mut reader = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = reader.next_line().await {
                if line.trim().is_empty() {
                    continue;
                }
                // Stderr lines are informational, not errors
                let _ = stderr_tx
                    .send(FromAgent::Token {
                        content: format!("{line}\n"),
                        is_thinking: false,
                    })
                    .await;
            }
        });

        // Writer task: serialize and send messages to agent stdin
        let (to_agent_tx, mut to_agent_rx) = mpsc::channel::<String>(64);
        tokio::spawn(async move {
            let mut stdin = stdin;
            while let Some(json_line) = to_agent_rx.recv().await {
                if stdin
                    .write_all(json_line.as_bytes())
                    .await
                    .is_err()
                {
                    break;
                }
                if stdin.write_all(b"\n").await.is_err() {
                    break;
                }
                let _ = stdin.flush().await;
            }
        });

        Ok((
            Self {
                child,
                tx: to_agent_tx,
            },
            from_agent_rx,
        ))
    }

    /// Send a message to the agent subprocess.
    pub async fn send(&self, msg: &ToAgent) -> Result<(), String> {
        let json = serde_json::to_string(msg).map_err(|e| format!("Serialize error: {e}"))?;
        self.tx
            .send(json)
            .await
            .map_err(|e| format!("Send error: {e}"))
    }

    /// Send interrupt signal to agent.
    pub async fn interrupt(&self) -> Result<(), String> {
        self.send(&ToAgent::Interrupt).await
    }

    /// Shut down the agent subprocess.
    pub async fn shutdown(mut self) {
        let _ = self.send(&ToAgent::Shutdown).await;
        // Give it a moment to clean up
        tokio::time::sleep(std::time::Duration::from_millis(200)).await;
        let _ = self.child.kill().await;
    }

    pub fn is_running(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }
}

fn find_run_agent() -> Result<PathBuf, String> {
    // Look for run_agent.py relative to the binary or cwd
    let candidates = [
        PathBuf::from("run_agent.py"),
        PathBuf::from("../run_agent.py"),
        {
            let mut p = std::env::current_exe().unwrap_or_default();
            p.pop(); // bin dir
            p.pop(); // project root
            p.push("run_agent.py");
            p
        },
    ];

    for p in &candidates {
        if p.exists() {
            return Ok(p.clone());
        }
    }

    Err("Could not find run_agent.py".into())
}

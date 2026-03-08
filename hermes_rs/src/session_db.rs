use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use rusqlite::types::{ToSql, Value as SqlValue};
use rusqlite::{params, Connection};
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

// ── Schema ───────────────────────────────────────────────────────────────

const SCHEMA_VERSION: i32 = 2;

const SCHEMA_SQL: &str = "
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    user_id TEXT,
    model TEXT,
    model_config TEXT,
    system_prompt TEXT,
    parent_session_id TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    end_reason TEXT,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    FOREIGN KEY (parent_session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    timestamp REAL NOT NULL,
    token_count INTEGER,
    finish_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, id);
";

const FTS_SQL: &str = "
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content=messages,
    content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
";

const SESSION_COLS: &[&str] = &[
    "id", "source", "user_id", "model", "model_config", "system_prompt",
    "parent_session_id", "started_at", "ended_at", "end_reason",
    "message_count", "tool_call_count", "input_tokens", "output_tokens",
];

const MESSAGE_COLS: &[&str] = &[
    "id", "session_id", "role", "content", "tool_call_id",
    "tool_calls", "tool_name", "timestamp", "token_count", "finish_reason",
];

const DEFAULT_SOURCES: &[&str] = &["cli", "telegram", "discord", "whatsapp", "slack"];

// ── Helpers ──────────────────────────────────────────────────────────────

fn now_ts() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64()
}

fn map_err(e: rusqlite::Error) -> PyErr {
    PyRuntimeError::new_err(format!("SQLite error: {e}"))
}

fn lock_err() -> PyErr {
    PyRuntimeError::new_err("Database mutex poisoned")
}

fn default_db_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".into());
    PathBuf::from(home)
        .join(".hermes-lite")
        .join("state.db")
}

fn extract_row(row: &rusqlite::Row, count: usize) -> rusqlite::Result<Vec<SqlValue>> {
    (0..count).map(|i| row.get(i)).collect()
}

fn values_to_dict<'py>(
    py: Python<'py>,
    cols: &[&str],
    vals: &[SqlValue],
) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    for (&col, val) in cols.iter().zip(vals.iter()) {
        match val {
            SqlValue::Null => dict.set_item(col, py.None())?,
            SqlValue::Integer(n) => dict.set_item(col, *n)?,
            SqlValue::Real(f) => dict.set_item(col, *f)?,
            SqlValue::Text(s) => dict.set_item(col, s.as_str())?,
            SqlValue::Blob(b) => dict.set_item(col, b.as_slice())?,
        }
    }
    Ok(dict)
}

fn py_to_json_str(py: Python<'_>, obj: &Bound<'_, PyAny>) -> PyResult<Option<String>> {
    if obj.is_none() {
        return Ok(None);
    }
    let json_mod = py.import("json")?;
    let s: String = json_mod.call_method1("dumps", (obj,))?.extract()?;
    Ok(Some(s))
}

fn json_str_to_py(py: Python<'_>, s: &str) -> Option<PyObject> {
    let json_mod = py.import("json").ok()?;
    json_mod.call_method1("loads", (s,)).ok().map(|v| v.unbind())
}

// ── Internal query helpers (avoid re-entrant mutex lock) ─────────────────

fn get_session_impl(
    py: Python<'_>,
    conn: &Connection,
    session_id: &str,
) -> PyResult<Option<PyObject>> {
    let mut stmt = conn
        .prepare(
            "SELECT id, source, user_id, model, model_config, system_prompt, \
             parent_session_id, started_at, ended_at, end_reason, \
             message_count, tool_call_count, input_tokens, output_tokens \
             FROM sessions WHERE id = ?",
        )
        .map_err(map_err)?;

    match stmt.query_row(params![session_id], |row| {
        extract_row(row, SESSION_COLS.len())
    }) {
        Ok(vals) => {
            let dict = values_to_dict(py, SESSION_COLS, &vals)?;
            Ok(Some(dict.into_any().unbind()))
        }
        Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
        Err(e) => Err(map_err(e)),
    }
}

fn get_messages_impl(
    py: Python<'_>,
    conn: &Connection,
    session_id: &str,
) -> PyResult<Vec<PyObject>> {
    let rows: Vec<Vec<SqlValue>> = {
        let mut stmt = conn
            .prepare(
                "SELECT id, session_id, role, content, tool_call_id, \
                 tool_calls, tool_name, timestamp, token_count, finish_reason \
                 FROM messages WHERE session_id = ? ORDER BY timestamp, id",
            )
            .map_err(map_err)?;
        let mapped = stmt.query_map(params![session_id], |row| {
            extract_row(row, MESSAGE_COLS.len())
        })
        .map_err(map_err)?;
        mapped.collect::<Result<Vec<_>, _>>().map_err(map_err)?
    };

    let mut result = Vec::with_capacity(rows.len());
    for vals in &rows {
        let dict = values_to_dict(py, MESSAGE_COLS, vals)?;
        // Deserialize tool_calls JSON
        if let SqlValue::Text(ref tc_str) = vals[5] {
            if let Some(tc_obj) = json_str_to_py(py, tc_str) {
                dict.set_item("tool_calls", tc_obj)?;
            }
        }
        result.push(dict.into_any().unbind());
    }
    Ok(result)
}

fn search_sessions_impl(
    py: Python<'_>,
    conn: &Connection,
    source: Option<&str>,
    limit: i32,
    offset: i32,
) -> PyResult<Vec<PyObject>> {
    let rows: Vec<Vec<SqlValue>> = if let Some(src) = source {
        let mut stmt = conn
            .prepare(
                "SELECT id, source, user_id, model, model_config, system_prompt, \
                 parent_session_id, started_at, ended_at, end_reason, \
                 message_count, tool_call_count, input_tokens, output_tokens \
                 FROM sessions WHERE source = ? ORDER BY started_at DESC LIMIT ? OFFSET ?",
            )
            .map_err(map_err)?;
        let mapped = stmt.query_map(params![src, limit, offset], |row| {
            extract_row(row, SESSION_COLS.len())
        })
        .map_err(map_err)?;
        mapped.collect::<Result<Vec<_>, _>>().map_err(map_err)?
    } else {
        let mut stmt = conn
            .prepare(
                "SELECT id, source, user_id, model, model_config, system_prompt, \
                 parent_session_id, started_at, ended_at, end_reason, \
                 message_count, tool_call_count, input_tokens, output_tokens \
                 FROM sessions ORDER BY started_at DESC LIMIT ? OFFSET ?",
            )
            .map_err(map_err)?;
        let mapped = stmt.query_map(params![limit, offset], |row| {
            extract_row(row, SESSION_COLS.len())
        })
        .map_err(map_err)?;
        mapped.collect::<Result<Vec<_>, _>>().map_err(map_err)?
    };

    let mut result = Vec::with_capacity(rows.len());
    for vals in &rows {
        result.push(values_to_dict(py, SESSION_COLS, vals)?.into_any().unbind());
    }
    Ok(result)
}

// ── RustSessionDB ────────────────────────────────────────────────────────

#[pyclass]
pub struct RustSessionDB {
    conn: Mutex<Connection>,
}

impl RustSessionDB {
    fn init_schema(conn: &Connection) -> rusqlite::Result<()> {
        conn.execute_batch(SCHEMA_SQL)?;

        let version: i32 = conn
            .query_row(
                "SELECT version FROM schema_version LIMIT 1",
                [],
                |row| row.get(0),
            )
            .unwrap_or(0);

        if version == 0 {
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                params![SCHEMA_VERSION],
            )?;
        } else if version < 2 {
            let _ = conn.execute("ALTER TABLE messages ADD COLUMN finish_reason TEXT", []);
            conn.execute(
                "UPDATE schema_version SET version = ?",
                params![SCHEMA_VERSION],
            )?;
        }

        // FTS5 (idempotent)
        if conn
            .execute("SELECT * FROM messages_fts LIMIT 0", [])
            .is_err()
        {
            conn.execute_batch(FTS_SQL)?;
        }

        Ok(())
    }
}

#[pymethods]
impl RustSessionDB {
    #[new]
    #[pyo3(signature = (db_path=None))]
    fn new(db_path: Option<String>) -> PyResult<Self> {
        let path = match db_path {
            Some(p) => PathBuf::from(p),
            None => default_db_path(),
        };

        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| PyRuntimeError::new_err(format!("mkdir: {e}")))?;
        }

        let conn = Connection::open(&path).map_err(map_err)?;
        conn.busy_timeout(std::time::Duration::from_secs(10))
            .map_err(map_err)?;
        conn.execute_batch(
            "PRAGMA journal_mode=WAL;\
             PRAGMA foreign_keys=ON;\
             PRAGMA synchronous=NORMAL;\
             PRAGMA mmap_size=30000000;\
             PRAGMA temp_store=MEMORY;\
             PRAGMA journal_size_limit=67108864;",
        )
        .map_err(map_err)?;

        Self::init_schema(&conn).map_err(map_err)?;

        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    fn close(&self) -> PyResult<()> {
        Ok(()) // Connection drops with struct; no-op for compat
    }

    // ── Session lifecycle ────────────────────────────────────────────────

    #[pyo3(signature = (session_id, source, model=None, model_config=None, system_prompt=None, user_id=None, parent_session_id=None))]
    fn create_session(
        &self,
        py: Python<'_>,
        session_id: String,
        source: String,
        model: Option<String>,
        model_config: Option<PyObject>,
        system_prompt: Option<String>,
        user_id: Option<String>,
        parent_session_id: Option<String>,
    ) -> PyResult<String> {
        let mc_json: Option<String> = match model_config {
            Some(ref obj) => py_to_json_str(py, obj.bind(py))?,
            None => None,
        };

        let conn = self.conn.lock().map_err(|_| lock_err())?;
        conn.execute(
            "INSERT INTO sessions (id, source, user_id, model, model_config, \
             system_prompt, parent_session_id, started_at) \
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            params![
                session_id,
                source,
                user_id,
                model,
                mc_json,
                system_prompt,
                parent_session_id,
                now_ts()
            ],
        )
        .map_err(map_err)?;

        Ok(session_id)
    }

    fn end_session(&self, session_id: String, end_reason: String) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|_| lock_err())?;
        conn.execute(
            "UPDATE sessions SET ended_at = ?, end_reason = ? WHERE id = ?",
            params![now_ts(), end_reason, session_id],
        )
        .map_err(map_err)?;
        Ok(())
    }

    fn reopen_session(&self, session_id: String) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|_| lock_err())?;
        conn.execute(
            "UPDATE sessions SET ended_at = NULL, end_reason = NULL WHERE id = ?",
            params![session_id],
        )
        .map_err(map_err)?;
        Ok(())
    }

    fn update_system_prompt(&self, session_id: String, system_prompt: String) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|_| lock_err())?;
        conn.execute(
            "UPDATE sessions SET system_prompt = ? WHERE id = ?",
            params![system_prompt, session_id],
        )
        .map_err(map_err)?;
        Ok(())
    }

    #[pyo3(signature = (session_id, input_tokens=0, output_tokens=0))]
    fn update_token_counts(
        &self,
        session_id: String,
        input_tokens: i32,
        output_tokens: i32,
    ) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|_| lock_err())?;
        conn.execute(
            "UPDATE sessions SET input_tokens = input_tokens + ?, \
             output_tokens = output_tokens + ? WHERE id = ?",
            params![input_tokens, output_tokens, session_id],
        )
        .map_err(map_err)?;
        Ok(())
    }

    fn get_session(&self, py: Python<'_>, session_id: String) -> PyResult<Option<PyObject>> {
        let conn = self.conn.lock().map_err(|_| lock_err())?;
        get_session_impl(py, &conn, &session_id)
    }

    // ── Messages ─────────────────────────────────────────────────────────

    #[pyo3(signature = (session_id, role, content=None, tool_name=None, tool_calls=None, tool_call_id=None, token_count=None, finish_reason=None))]
    fn append_message(
        &self,
        py: Python<'_>,
        session_id: String,
        role: String,
        content: Option<String>,
        tool_name: Option<String>,
        tool_calls: Option<PyObject>,
        tool_call_id: Option<String>,
        token_count: Option<i32>,
        finish_reason: Option<String>,
    ) -> PyResult<i64> {
        let tc_json: Option<String> = match tool_calls {
            Some(ref obj) => py_to_json_str(py, obj.bind(py))?,
            None => None,
        };

        let conn = self.conn.lock().map_err(|_| lock_err())?;
        conn.execute(
            "INSERT INTO messages (session_id, role, content, tool_call_id, \
             tool_calls, tool_name, timestamp, token_count, finish_reason) \
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            params![
                session_id,
                role,
                content,
                tool_call_id,
                tc_json,
                tool_name,
                now_ts(),
                token_count,
                finish_reason
            ],
        )
        .map_err(map_err)?;

        let msg_id = conn.last_insert_rowid();

        let is_tool = role == "tool" || tc_json.is_some();
        if is_tool {
            conn.execute(
                "UPDATE sessions SET message_count = message_count + 1, \
                 tool_call_count = tool_call_count + 1 WHERE id = ?",
                params![session_id],
            )
            .map_err(map_err)?;
        } else {
            conn.execute(
                "UPDATE sessions SET message_count = message_count + 1 WHERE id = ?",
                params![session_id],
            )
            .map_err(map_err)?;
        }

        Ok(msg_id)
    }

    fn get_messages(&self, py: Python<'_>, session_id: String) -> PyResult<Vec<PyObject>> {
        let conn = self.conn.lock().map_err(|_| lock_err())?;
        get_messages_impl(py, &conn, &session_id)
    }

    fn get_messages_as_conversation(
        &self,
        py: Python<'_>,
        session_id: String,
    ) -> PyResult<Vec<PyObject>> {
        let conn = self.conn.lock().map_err(|_| lock_err())?;

        let rows: Vec<(String, Option<String>, Option<String>, Option<String>, Option<String>)> = {
            let mut stmt = conn
                .prepare(
                    "SELECT role, content, tool_call_id, tool_calls, tool_name \
                     FROM messages WHERE session_id = ? ORDER BY timestamp, id",
                )
                .map_err(map_err)?;
            let mapped = stmt.query_map(params![session_id], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, Option<String>>(1)?,
                    row.get::<_, Option<String>>(2)?,
                    row.get::<_, Option<String>>(3)?,
                    row.get::<_, Option<String>>(4)?,
                ))
            })
            .map_err(map_err)?;
            mapped.collect::<Result<Vec<_>, _>>().map_err(map_err)?
        };

        let mut result = Vec::with_capacity(rows.len());
        for (role, content, tool_call_id, tool_calls_str, tool_name) in &rows {
            let dict = PyDict::new(py);
            dict.set_item("role", role)?;
            dict.set_item("content", content.as_deref())?;

            if let Some(tci) = tool_call_id {
                if !tci.is_empty() {
                    dict.set_item("tool_call_id", tci)?;
                }
            }
            if let Some(tn) = tool_name {
                if !tn.is_empty() {
                    dict.set_item("tool_name", tn)?;
                }
            }
            if let Some(tc_str) = tool_calls_str {
                if !tc_str.is_empty() {
                    match json_str_to_py(py, tc_str) {
                        Some(tc_obj) => dict.set_item("tool_calls", tc_obj)?,
                        None => dict.set_item("tool_calls", tc_str.as_str())?,
                    }
                }
            }

            result.push(dict.into_any().unbind());
        }
        Ok(result)
    }

    fn clear_messages(&self, session_id: String) -> PyResult<()> {
        let conn = self.conn.lock().map_err(|_| lock_err())?;
        conn.execute(
            "DELETE FROM messages WHERE session_id = ?",
            params![session_id],
        )
        .map_err(map_err)?;
        conn.execute(
            "UPDATE sessions SET message_count = 0, tool_call_count = 0 WHERE id = ?",
            params![session_id],
        )
        .map_err(map_err)?;
        Ok(())
    }

    // ── Search ───────────────────────────────────────────────────────────

    #[pyo3(signature = (query, source_filter=None, role_filter=None, limit=20, offset=0))]
    fn search_messages(
        &self,
        py: Python<'_>,
        query: String,
        source_filter: Option<Vec<String>>,
        role_filter: Option<Vec<String>>,
        limit: i32,
        offset: i32,
    ) -> PyResult<Vec<PyObject>> {
        if query.trim().is_empty() {
            return Ok(Vec::new());
        }

        let sources: Vec<String> = source_filter
            .unwrap_or_else(|| DEFAULT_SOURCES.iter().map(|s| s.to_string()).collect());

        let source_ph: String = sources.iter().map(|_| "?").collect::<Vec<_>>().join(", ");
        let mut sql = format!(
            "SELECT m.id, m.session_id, m.role, \
             snippet(messages_fts, 0, '>>>', '<<<', '...', 40) AS snippet, \
             m.content, m.timestamp, m.tool_name, s.source, s.model, \
             s.started_at AS session_started \
             FROM messages_fts \
             JOIN messages m ON m.id = messages_fts.rowid \
             JOIN sessions s ON s.id = m.session_id \
             WHERE messages_fts MATCH ? AND s.source IN ({source_ph})"
        );

        let mut sql_params: Vec<SqlValue> = Vec::new();
        sql_params.push(SqlValue::Text(query));
        for s in &sources {
            sql_params.push(SqlValue::Text(s.clone()));
        }

        if let Some(ref roles) = role_filter {
            let role_ph: String = roles.iter().map(|_| "?").collect::<Vec<_>>().join(", ");
            sql.push_str(&format!(" AND m.role IN ({role_ph})"));
            for r in roles {
                sql_params.push(SqlValue::Text(r.clone()));
            }
        }

        sql.push_str(" ORDER BY rank LIMIT ? OFFSET ?");
        sql_params.push(SqlValue::Integer(limit as i64));
        sql_params.push(SqlValue::Integer(offset as i64));

        let conn = self.conn.lock().map_err(|_| lock_err())?;

        let search_cols = &[
            "id",
            "session_id",
            "role",
            "snippet",
            "content",
            "timestamp",
            "tool_name",
            "source",
            "model",
            "session_started",
        ];

        // Collect FTS matches first (release stmt borrow before context queries)
        let matches: Vec<Vec<SqlValue>> = {
            let refs: Vec<&dyn ToSql> =
                sql_params.iter().map(|v| v as &dyn ToSql).collect();
            let mut stmt = conn.prepare(&sql).map_err(map_err)?;
            let mapped = stmt.query_map(refs.as_slice(), |row| extract_row(row, search_cols.len()))
                .map_err(map_err)?;
            mapped.collect::<Result<Vec<_>, _>>().map_err(map_err)?
        };

        let mut result = Vec::with_capacity(matches.len());
        for vals in &matches {
            let dict = values_to_dict(py, search_cols, vals)?;
            // Remove full content, keep snippet
            let _ = dict.del_item("content");

            // Fetch context (1 message before/after)
            let session_id = match &vals[1] {
                SqlValue::Text(s) => s.as_str(),
                _ => "",
            };
            let msg_id = match &vals[0] {
                SqlValue::Integer(n) => *n,
                _ => 0,
            };

            let ctx_rows: Vec<(String, Option<String>)> = {
                let mut ctx_stmt = conn
                    .prepare(
                        "SELECT role, content FROM messages \
                         WHERE session_id = ? AND id >= ? AND id <= ? ORDER BY id",
                    )
                    .map_err(map_err)?;
                let mapped = ctx_stmt
                    .query_map(params![session_id, msg_id - 1, msg_id + 1], |row| {
                        Ok((
                            row.get::<_, String>(0)?,
                            row.get::<_, Option<String>>(1)?,
                        ))
                    })
                    .map_err(map_err)?;
                mapped.collect::<Result<Vec<_>, _>>().map_err(map_err)?
            };

            let context = PyList::empty(py);
            for (role, content) in &ctx_rows {
                let ctx_dict = PyDict::new(py);
                ctx_dict.set_item("role", role)?;
                let truncated: String =
                    content.as_deref().unwrap_or("").chars().take(200).collect();
                ctx_dict.set_item("content", &truncated)?;
                context.append(ctx_dict)?;
            }
            dict.set_item("context", context)?;

            result.push(dict.into_any().unbind());
        }

        Ok(result)
    }

    #[pyo3(signature = (source=None, limit=20, offset=0))]
    fn search_sessions(
        &self,
        py: Python<'_>,
        source: Option<String>,
        limit: i32,
        offset: i32,
    ) -> PyResult<Vec<PyObject>> {
        let conn = self.conn.lock().map_err(|_| lock_err())?;
        search_sessions_impl(py, &conn, source.as_deref(), limit, offset)
    }

    // ── Counts ───────────────────────────────────────────────────────────

    #[pyo3(signature = (source=None))]
    fn session_count(&self, source: Option<String>) -> PyResult<i32> {
        let conn = self.conn.lock().map_err(|_| lock_err())?;
        let count: i32 = match source {
            Some(s) => conn.query_row(
                "SELECT COUNT(*) FROM sessions WHERE source = ?",
                params![s],
                |row| row.get(0),
            ),
            None => conn.query_row("SELECT COUNT(*) FROM sessions", [], |row| row.get(0)),
        }
        .map_err(map_err)?;
        Ok(count)
    }

    #[pyo3(signature = (session_id=None))]
    fn message_count(&self, session_id: Option<String>) -> PyResult<i32> {
        let conn = self.conn.lock().map_err(|_| lock_err())?;
        let count: i32 = match session_id {
            Some(sid) => conn.query_row(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?",
                params![sid],
                |row| row.get(0),
            ),
            None => conn.query_row("SELECT COUNT(*) FROM messages", [], |row| row.get(0)),
        }
        .map_err(map_err)?;
        Ok(count)
    }

    // ── Export ────────────────────────────────────────────────────────────

    fn export_session(&self, py: Python<'_>, session_id: String) -> PyResult<Option<PyObject>> {
        let conn = self.conn.lock().map_err(|_| lock_err())?;
        let session = get_session_impl(py, &conn, &session_id)?;
        match session {
            None => Ok(None),
            Some(session_obj) => {
                let messages = get_messages_impl(py, &conn, &session_id)?;
                let bound = session_obj.bind(py);
                let dict = bound
                    .downcast::<PyDict>()
                    .map_err(|e| PyRuntimeError::new_err(format!("{e}")))?;
                dict.set_item("messages", messages)?;
                Ok(Some(session_obj))
            }
        }
    }

    #[pyo3(signature = (source=None))]
    fn export_all(&self, py: Python<'_>, source: Option<String>) -> PyResult<Vec<PyObject>> {
        let conn = self.conn.lock().map_err(|_| lock_err())?;
        let sessions = search_sessions_impl(py, &conn, source.as_deref(), 100_000, 0)?;
        let mut result = Vec::with_capacity(sessions.len());
        for session_obj in sessions {
            let bound = session_obj.bind(py);
            let dict = bound
                .downcast::<PyDict>()
                .map_err(|e| PyRuntimeError::new_err(format!("{e}")))?;
            let sid: String = dict
                .get_item("id")?
                .ok_or_else(|| PyRuntimeError::new_err("missing id"))?
                .extract()?;
            let messages = get_messages_impl(py, &conn, &sid)?;
            dict.set_item("messages", messages)?;
            result.push(session_obj);
        }
        Ok(result)
    }

    // ── Delete / Prune ───────────────────────────────────────────────────

    fn delete_session(&self, session_id: String) -> PyResult<bool> {
        let conn = self.conn.lock().map_err(|_| lock_err())?;
        let count: i32 = conn
            .query_row(
                "SELECT COUNT(*) FROM sessions WHERE id = ?",
                params![&session_id],
                |row| row.get(0),
            )
            .map_err(map_err)?;

        if count == 0 {
            return Ok(false);
        }

        conn.execute(
            "DELETE FROM messages WHERE session_id = ?",
            params![session_id],
        )
        .map_err(map_err)?;
        conn.execute("DELETE FROM sessions WHERE id = ?", params![session_id])
            .map_err(map_err)?;

        Ok(true)
    }

    #[pyo3(signature = (older_than_days=90, source=None))]
    fn prune_sessions(&self, older_than_days: i32, source: Option<String>) -> PyResult<i32> {
        let cutoff = now_ts() - (older_than_days as f64 * 86400.0);
        let conn = self.conn.lock().map_err(|_| lock_err())?;

        let session_ids: Vec<String> = if let Some(ref src) = source {
            let mut stmt = conn
                .prepare(
                    "SELECT id FROM sessions \
                     WHERE started_at < ? AND ended_at IS NOT NULL AND source = ?",
                )
                .map_err(map_err)?;
            let mapped = stmt.query_map(params![cutoff, src], |row| row.get(0))
                .map_err(map_err)?;
            mapped.filter_map(|r| r.ok()).collect()
        } else {
            let mut stmt = conn
                .prepare(
                    "SELECT id FROM sessions \
                     WHERE started_at < ? AND ended_at IS NOT NULL",
                )
                .map_err(map_err)?;
            let mapped = stmt.query_map(params![cutoff], |row| row.get(0))
                .map_err(map_err)?;
            mapped.filter_map(|r| r.ok()).collect()
        };

        let count = session_ids.len() as i32;
        for sid in &session_ids {
            conn.execute("DELETE FROM messages WHERE session_id = ?", params![sid])
                .map_err(map_err)?;
            conn.execute("DELETE FROM sessions WHERE id = ?", params![sid])
                .map_err(map_err)?;
        }

        Ok(count)
    }

    // ── Batch operations (new, not in Python) ────────────────────────────

    fn append_messages(
        &self,
        py: Python<'_>,
        session_id: String,
        messages: Vec<Bound<'_, PyDict>>,
    ) -> PyResult<Vec<i64>> {
        let mut conn = self.conn.lock().map_err(|_| lock_err())?;
        let tx = conn.transaction().map_err(map_err)?;

        let mut ids = Vec::with_capacity(messages.len());
        let mut tool_count = 0i32;

        for msg in &messages {
            let role: String = msg
                .get_item("role")?
                .ok_or_else(|| PyRuntimeError::new_err("missing role"))?
                .extract()?;
            let content: Option<String> = msg
                .get_item("content")?
                .and_then(|v| v.extract().ok());
            let tool_name: Option<String> = msg
                .get_item("tool_name")?
                .and_then(|v| v.extract().ok());
            let tool_call_id: Option<String> = msg
                .get_item("tool_call_id")?
                .and_then(|v| v.extract().ok());
            let token_count: Option<i32> = msg
                .get_item("token_count")?
                .and_then(|v| v.extract().ok());
            let finish_reason: Option<String> = msg
                .get_item("finish_reason")?
                .and_then(|v| v.extract().ok());

            let tc_json: Option<String> = match msg.get_item("tool_calls")? {
                Some(obj) if !obj.is_none() => py_to_json_str(py, &obj)?,
                _ => None,
            };

            if role == "tool" || tc_json.is_some() {
                tool_count += 1;
            }

            tx.execute(
                "INSERT INTO messages (session_id, role, content, tool_call_id, \
                 tool_calls, tool_name, timestamp, token_count, finish_reason) \
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                params![
                    session_id,
                    role,
                    content,
                    tool_call_id,
                    tc_json,
                    tool_name,
                    now_ts(),
                    token_count,
                    finish_reason
                ],
            )
            .map_err(map_err)?;

            ids.push(tx.last_insert_rowid());
        }

        let total = ids.len() as i32;
        if tool_count > 0 {
            tx.execute(
                "UPDATE sessions SET message_count = message_count + ?, \
                 tool_call_count = tool_call_count + ? WHERE id = ?",
                params![total, tool_count, session_id],
            )
            .map_err(map_err)?;
        } else if total > 0 {
            tx.execute(
                "UPDATE sessions SET message_count = message_count + ? WHERE id = ?",
                params![total, session_id],
            )
            .map_err(map_err)?;
        }

        tx.commit().map_err(map_err)?;
        Ok(ids)
    }
}

/// Mention parser for @agent and @all directives in user input.
///
/// Supports:
///   @a1 message       → route to agent "a1"
///   @a2! message      → route to "a2" and pull response back
///   @all message      → broadcast to all agents

#[derive(Debug, Clone, PartialEq)]
pub enum MentionTarget {
    Agent {
        name: String,
        pull_back: bool, // true if @name! (with trailing !)
    },
    All, // @all — broadcast
}

#[derive(Debug, Clone)]
pub struct ParsedInput {
    pub mention: Option<MentionTarget>,
    pub message: String, // the actual message text after the @mention
}

/// Parse user input for a leading @mention.
///
/// Rules:
/// - Input must start with `@` (after trimming) to trigger mention parsing.
/// - The token immediately after `@` is the agent name (alphanumeric / underscore / hyphen).
/// - A trailing `!` on the name means "pull back" (inject the response into the current pane).
/// - `@all` is a broadcast mention.
/// - There must be a space separating the @name from the message body.
/// - If no valid mention is found, the entire input is returned as-is with `mention: None`.
pub fn parse_input(input: &str) -> ParsedInput {
    let trimmed = input.trim();

    if !trimmed.starts_with('@') {
        return ParsedInput {
            mention: None,
            message: trimmed.to_string(),
        };
    }

    let rest = &trimmed[1..]; // skip the '@'

    // Must have a space separating name from message.
    let space_pos = match rest.find(' ') {
        Some(pos) => pos,
        None => {
            // No space — treat the whole thing as literal text (e.g. "@" alone, "@nospc").
            return ParsedInput {
                mention: None,
                message: trimmed.to_string(),
            };
        }
    };

    let name_part = &rest[..space_pos];

    // Empty name part (e.g. "@ hello") — not a valid mention.
    if name_part.is_empty() {
        return ParsedInput {
            mention: None,
            message: trimmed.to_string(),
        };
    }

    // Detect pull-back flag.
    let (name, pull_back) = if name_part.ends_with('!') {
        let n = &name_part[..name_part.len() - 1];
        if n.is_empty() {
            // "@! something" — not a valid mention.
            return ParsedInput {
                mention: None,
                message: trimmed.to_string(),
            };
        }
        (n, true)
    } else {
        (name_part, false)
    };

    // Validate: name must be non-empty alphanumeric / underscore / hyphen.
    if !name
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
    {
        return ParsedInput {
            mention: None,
            message: trimmed.to_string(),
        };
    }

    let message = rest[space_pos + 1..].trim().to_string();

    // Empty message after mention — still a valid mention (agent gets empty task).
    let target = if name.eq_ignore_ascii_case("all") {
        MentionTarget::All
    } else {
        MentionTarget::Agent {
            name: name.to_string(),
            pull_back,
        }
    };

    ParsedInput {
        mention: Some(target),
        message,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plain_message_no_mention() {
        let p = parse_input("hello world");
        assert!(p.mention.is_none());
        assert_eq!(p.message, "hello world");
    }

    #[test]
    fn agent_mention_simple() {
        let p = parse_input("@a1 hello");
        assert_eq!(
            p.mention,
            Some(MentionTarget::Agent {
                name: "a1".into(),
                pull_back: false,
            })
        );
        assert_eq!(p.message, "hello");
    }

    #[test]
    fn agent_mention_pull_back() {
        let p = parse_input("@a2! what's up");
        assert_eq!(
            p.mention,
            Some(MentionTarget::Agent {
                name: "a2".into(),
                pull_back: true,
            })
        );
        assert_eq!(p.message, "what's up");
    }

    #[test]
    fn broadcast_all() {
        let p = parse_input("@all do this");
        assert_eq!(p.mention, Some(MentionTarget::All));
        assert_eq!(p.message, "do this");
    }

    #[test]
    fn broadcast_all_case_insensitive() {
        let p = parse_input("@ALL refactor everything");
        assert_eq!(p.mention, Some(MentionTarget::All));
        assert_eq!(p.message, "refactor everything");
    }

    #[test]
    fn custom_name_with_spaces() {
        let p = parse_input("@researcher summarize the API docs");
        assert_eq!(
            p.mention,
            Some(MentionTarget::Agent {
                name: "researcher".into(),
                pull_back: false,
            })
        );
        assert_eq!(p.message, "summarize the API docs");
    }

    #[test]
    fn custom_name_with_pull_back() {
        let p = parse_input("@my-agent! do the thing");
        assert_eq!(
            p.mention,
            Some(MentionTarget::Agent {
                name: "my-agent".into(),
                pull_back: true,
            })
        );
        assert_eq!(p.message, "do the thing");
    }

    #[test]
    fn at_alone_is_literal() {
        let p = parse_input("@");
        assert!(p.mention.is_none());
        assert_eq!(p.message, "@");
    }

    #[test]
    fn at_no_space_is_literal() {
        let p = parse_input("@nospacemessage");
        assert!(p.mention.is_none());
        assert_eq!(p.message, "@nospacemessage");
    }

    #[test]
    fn double_at_is_literal() {
        let p = parse_input("@@ something");
        assert!(p.mention.is_none());
        assert_eq!(p.message, "@@ something");
    }

    #[test]
    fn empty_input() {
        let p = parse_input("");
        assert!(p.mention.is_none());
        assert_eq!(p.message, "");
    }

    #[test]
    fn whitespace_only() {
        let p = parse_input("   ");
        assert!(p.mention.is_none());
        assert_eq!(p.message, "");
    }

    #[test]
    fn at_space_message_no_name() {
        // "@ hello" — empty name, not valid.
        let p = parse_input("@ hello");
        assert!(p.mention.is_none());
        assert_eq!(p.message, "@ hello");
    }

    #[test]
    fn at_bang_space_message() {
        // "@! hello" — bang with no name, not valid.
        let p = parse_input("@! hello");
        assert!(p.mention.is_none());
        assert_eq!(p.message, "@! hello");
    }

    #[test]
    fn leading_whitespace_trimmed() {
        let p = parse_input("  @a1 hello  ");
        assert_eq!(
            p.mention,
            Some(MentionTarget::Agent {
                name: "a1".into(),
                pull_back: false,
            })
        );
        assert_eq!(p.message, "hello");
    }

    #[test]
    fn mention_with_empty_message_body() {
        // "@a1 " trims to "@a1" — no space separator, so treated as literal.
        let p = parse_input("@a1 ");
        assert!(p.mention.is_none());
        assert_eq!(p.message, "@a1");
    }

    #[test]
    fn mention_with_whitespace_only_message() {
        // "@a1  " trims to "@a1" — same as above.
        let p = parse_input("@a1  ");
        assert!(p.mention.is_none());
        assert_eq!(p.message, "@a1");
    }

    #[test]
    fn mention_with_real_empty_body() {
        // "@a1 " won't work, but "@a1 x" does — test with minimal message.
        let p = parse_input("@a1 x");
        assert_eq!(
            p.mention,
            Some(MentionTarget::Agent {
                name: "a1".into(),
                pull_back: false,
            })
        );
        assert_eq!(p.message, "x");
    }

    #[test]
    fn name_with_underscores() {
        let p = parse_input("@code_reviewer check imports");
        assert_eq!(
            p.mention,
            Some(MentionTarget::Agent {
                name: "code_reviewer".into(),
                pull_back: false,
            })
        );
        assert_eq!(p.message, "check imports");
    }
}

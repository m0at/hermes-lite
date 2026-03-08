"""
Configuration management for hermes-lite.

Config files are stored in ~/.hermes-lite/ by default:
- ~/.hermes-lite/config.yaml  - All settings (model, toolsets, terminal, etc.)
- ~/.hermes-lite/.env         - API keys and secrets

This module provides:
- hermes-lite config          - Show current configuration
- hermes-lite config edit     - Open config in editor
- hermes-lite config set      - Set a specific value
- hermes-lite setup           - Re-run setup wizard
"""

import os
import platform
import sys
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

_IS_WINDOWS = platform.system() == "Windows"

import yaml

from hermes_cli.colors import Colors, color
from hermes_constants import DEFAULT_HERMES_HOME


# =============================================================================
# Config paths
# =============================================================================

def get_hermes_home() -> Path:
    """Get the hermes-lite home directory (~/.hermes-lite by default)."""
    return Path(os.getenv("HERMES_HOME", DEFAULT_HERMES_HOME))

def get_config_path() -> Path:
    """Get the main config file path."""
    return get_hermes_home() / "config.yaml"

def get_env_path() -> Path:
    """Get the .env file path (for API keys)."""
    return get_hermes_home() / ".env"

def get_project_root() -> Path:
    """Get the project installation directory."""
    return Path(__file__).parent.parent.resolve()

def ensure_hermes_home():
    """Ensure the hermes-lite home directory structure exists."""
    home = get_hermes_home()
    (home / "sessions").mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(parents=True, exist_ok=True)
    (home / "images").mkdir(parents=True, exist_ok=True)
    (home / "pastes").mkdir(parents=True, exist_ok=True)


# =============================================================================
# Config loading/saving
# =============================================================================

DEFAULT_CONFIG = {
    "model": {
        "default": "claude-sonnet-4-5-20250929",
        "provider": "anthropic",
    },
    "toolsets": ["hermes-lite-cli"],
    "max_turns": 80,
    
    "terminal": {
        "backend": "local",
        "cwd": ".",  # Use current directory
        "timeout": 180,
    },
    
    "compression": {
        "enabled": True,
        "threshold": 0.85,
        "summary_model": "claude-haiku-4-5",
    },
    
    "memory": {
        "memory_enabled": True,
        "user_profile_enabled": True,
        "memory_char_limit": 2200,
        "user_char_limit": 1375,
        "nudge_interval": 10,
        "flush_min_turns": 6,
    },

    "display": {
        "compact": False,
        "personality": "kawaii",
    },
    
    # Ephemeral prefill messages file — JSON list of {role, content} dicts
    # injected at the start of every API call for few-shot priming.
    # Never saved to sessions, logs, or trajectories.
    "prefill_messages_file": "",

    # Permanently allowed dangerous command patterns (added via "always" approval)
    "command_allowlist": [],
    
    # Config schema version - bump this when adding new required fields
    "_config_version": 1,
}

# =============================================================================
# Config Migration System
# =============================================================================

# Required environment variables with metadata for migration prompts.
# LLM provider is required but handled in the setup wizard's provider
# selection step (Anthropic or optional local endpoint), so this dict is
# intentionally empty — no single env var is universally required.
REQUIRED_ENV_VARS = {}

# hermes-lite intentionally keeps runtime configuration narrow.
OPTIONAL_ENV_VARS = {
    "ANTHROPIC_API_KEY": {
        "description": "Anthropic API key for Claude models",
        "prompt": "Anthropic API key",
        "url": "https://console.anthropic.com/settings/keys",
        "password": True,
        "category": "provider",
    },
    "OPENAI_BASE_URL": {
        "description": "Optional OpenAI-compatible local model endpoint",
        "prompt": "Local model base URL",
        "url": None,
        "password": False,
        "category": "provider",
        "advanced": True,
    },
    "OPENAI_API_KEY": {
        "description": "Optional API key for the local OpenAI-compatible endpoint",
        "prompt": "Local model API key",
        "url": None,
        "password": True,
        "category": "provider",
        "advanced": True,
    },
}


def get_missing_env_vars(required_only: bool = False) -> List[Dict[str, Any]]:
    """
    Check which environment variables are missing.
    
    Returns list of dicts with var info for missing variables.
    """
    missing = []
    
    # Check required vars
    for var_name, info in REQUIRED_ENV_VARS.items():
        if not get_env_value(var_name):
            missing.append({"name": var_name, **info, "is_required": True})
    
    # Check optional vars (if not required_only)
    if not required_only:
        for var_name, info in OPTIONAL_ENV_VARS.items():
            if not get_env_value(var_name):
                missing.append({"name": var_name, **info, "is_required": False})
    
    return missing


def _set_nested(config: dict, dotted_key: str, value):
    """Set a value at an arbitrarily nested dotted key path.

    Creates intermediate dicts as needed, e.g. ``_set_nested(c, "a.b.c", 1)``
    ensures ``c["a"]["b"]["c"] == 1``.
    """
    parts = dotted_key.split(".")
    current = config
    for part in parts[:-1]:
        if part not in current or not isinstance(current.get(part), dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def get_missing_config_fields() -> List[Dict[str, Any]]:
    """
    Check which config fields are missing or outdated (recursive).
    
    Walks the DEFAULT_CONFIG tree at arbitrary depth and reports any keys
    present in defaults but absent from the user's loaded config.
    """
    config = load_config()
    missing = []

    def _check(defaults: dict, current: dict, prefix: str = ""):
        for key, default_value in defaults.items():
            if key.startswith('_'):
                continue
            full_key = key if not prefix else f"{prefix}.{key}"
            if key not in current:
                missing.append({
                    "key": full_key,
                    "default": default_value,
                    "description": f"New config option: {full_key}",
                })
            elif isinstance(default_value, dict) and isinstance(current.get(key), dict):
                _check(default_value, current[key], full_key)

    _check(DEFAULT_CONFIG, config)
    return missing


def check_config_version() -> Tuple[int, int]:
    """
    Check config version.
    
    Returns (current_version, latest_version).
    """
    config = load_config()
    current = config.get("_config_version", 0)
    latest = DEFAULT_CONFIG.get("_config_version", 1)
    return current, latest


def migrate_config(interactive: bool = True, quiet: bool = False) -> Dict[str, Any]:
    """
    Migrate config to latest version, prompting for new required fields.
    
    Args:
        interactive: If True, prompt user for missing values
        quiet: If True, suppress output
        
    Returns:
        Dict with migration results: {"env_added": [...], "config_added": [...], "warnings": [...]}
    """
    results = {"env_added": [], "config_added": [], "warnings": []}
    
    # Check config version
    current_ver, latest_ver = check_config_version()
    
    # ── Version 3 → 4: migrate tool progress from .env to config.yaml ──
    if current_ver < 4:
        config = load_config()
        display = config.get("display", {})
        if not isinstance(display, dict):
            display = {}
        if "tool_progress" not in display:
            old_enabled = get_env_value("HERMES_TOOL_PROGRESS")
            old_mode = get_env_value("HERMES_TOOL_PROGRESS_MODE")
            if old_enabled and old_enabled.lower() in ("false", "0", "no"):
                display["tool_progress"] = "off"
                results["config_added"].append("display.tool_progress=off (from HERMES_TOOL_PROGRESS=false)")
            elif old_mode and old_mode.lower() in ("new", "all"):
                display["tool_progress"] = old_mode.lower()
                results["config_added"].append(f"display.tool_progress={old_mode.lower()} (from HERMES_TOOL_PROGRESS_MODE)")
            else:
                display["tool_progress"] = "all"
                results["config_added"].append("display.tool_progress=all (default)")
            config["display"] = display
            save_config(config)
            if not quiet:
                print(f"  ✓ Migrated tool progress to config.yaml: {display['tool_progress']}")
    
    if current_ver < latest_ver and not quiet:
        print(f"Config version: {current_ver} → {latest_ver}")
    
    # Check for missing required env vars
    missing_env = get_missing_env_vars(required_only=True)
    
    if missing_env and not quiet:
        print("\n⚠️  Missing required environment variables:")
        for var in missing_env:
            print(f"   • {var['name']}: {var['description']}")
    
    if interactive and missing_env:
        print("\nLet's configure them now:\n")
        for var in missing_env:
            if var.get("url"):
                print(f"  Get your key at: {var['url']}")
            
            if var.get("password"):
                import getpass
                value = getpass.getpass(f"  {var['prompt']}: ")
            else:
                value = input(f"  {var['prompt']}: ").strip()
            
            if value:
                save_env_value(var["name"], value)
                results["env_added"].append(var["name"])
                print(f"  ✓ Saved {var['name']}")
            else:
                results["warnings"].append(f"Skipped {var['name']} - some features may not work")
            print()
    
    # Check for missing optional env vars and offer to configure interactively
    # Skip "advanced" vars (like OPENAI_BASE_URL) -- those are for power users
    missing_optional = get_missing_env_vars(required_only=False)
    required_names = {v["name"] for v in missing_env} if missing_env else set()
    missing_optional = [
        v for v in missing_optional
        if v["name"] not in required_names and not v.get("advanced")
    ]
    
    if interactive and missing_optional:
        print("  Would you like to configure any optional keys now?")
        try:
            answer = input("  Configure optional keys? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        
        if answer in ("y", "yes"):
            print()
            for var in missing_optional:
                desc = var.get("description", "")
                if var.get("url"):
                    print(f"  {desc}")
                    print(f"  Get your key at: {var['url']}")
                else:
                    print(f"  {desc}")
                
                if var.get("password"):
                    import getpass
                    value = getpass.getpass(f"  {var['prompt']} (Enter to skip): ")
                else:
                    value = input(f"  {var['prompt']} (Enter to skip): ").strip()
                
                if value:
                    save_env_value(var["name"], value)
                    results["env_added"].append(var["name"])
                    print(f"  ✓ Saved {var['name']}")
                print()
    
    # Check for missing config fields
    missing_config = get_missing_config_fields()
    
    if missing_config:
        config = load_config()
        
        for field in missing_config:
            key = field["key"]
            default = field["default"]
            
            _set_nested(config, key, default)
            results["config_added"].append(key)
            if not quiet:
                print(f"  ✓ Added {key} = {default}")
        
        # Update version and save
        config["_config_version"] = latest_ver
        save_config(config)
    elif current_ver < latest_ver:
        # Just update version
        config = load_config()
        config["_config_version"] = latest_ver
        save_config(config)
    
    return results


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*, preserving nested defaults.

    Keys in *override* take precedence. If both values are dicts the merge
    recurses, so a user who overrides only ``tts.elevenlabs.voice_id`` will
    keep the default ``tts.elevenlabs.model_id`` intact.
    """
    result = base.copy()
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> Dict[str, Any]:
    """Load configuration from ~/.hermes-lite/config.yaml."""
    import copy
    config_path = get_config_path()
    
    config = copy.deepcopy(DEFAULT_CONFIG)
    
    if config_path.exists():
        try:
            with open(config_path) as f:
                user_config = yaml.safe_load(f) or {}
            
            config = _deep_merge(config, user_config)
        except Exception as e:
            print(f"Warning: Failed to load config: {e}")
    
    return config


def save_config(config: Dict[str, Any]):
    """Save configuration to ~/.hermes-lite/config.yaml."""
    ensure_hermes_home()
    config_path = get_config_path()
    
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def load_env() -> Dict[str, str]:
    """Load environment variables from ~/.hermes-lite/.env."""
    env_path = get_env_path()
    env_vars = {}
    
    if env_path.exists():
        # On Windows, open() defaults to the system locale (cp1252) which can
        # fail on UTF-8 .env files. Use explicit UTF-8 only on Windows.
        open_kw = {"encoding": "utf-8", "errors": "replace"} if _IS_WINDOWS else {}
        with open(env_path, **open_kw) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    env_vars[key.strip()] = value.strip().strip('"\'')
    
    return env_vars


def save_env_value(key: str, value: str):
    """Save or update a value in ~/.hermes-lite/.env."""
    ensure_hermes_home()
    env_path = get_env_path()
    
    # On Windows, open() defaults to the system locale (cp1252) which can
    # cause OSError errno 22 on UTF-8 .env files.
    read_kw = {"encoding": "utf-8", "errors": "replace"} if _IS_WINDOWS else {}
    write_kw = {"encoding": "utf-8"} if _IS_WINDOWS else {}

    lines = []
    if env_path.exists():
        with open(env_path, **read_kw) as f:
            lines = f.readlines()
    
    # Find and update or append
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    
    if not found:
        # Ensure there's a newline at the end of the file before appending
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{key}={value}\n")
    
    with open(env_path, 'w', **write_kw) as f:
        f.writelines(lines)


def get_env_value(key: str) -> Optional[str]:
    """Get a value from ~/.hermes-lite/.env or environment."""
    # Check environment first
    if key in os.environ:
        return os.environ[key]
    
    # Then check .env file
    env_vars = load_env()
    return env_vars.get(key)


# =============================================================================
# Config display
# =============================================================================

def redact_key(key: str) -> str:
    """Redact an API key for display."""
    if not key:
        return color("(not set)", Colors.DIM)
    if len(key) < 12:
        return "***"
    return key[:4] + "..." + key[-4:]


def show_config():
    """Display current configuration."""
    config = load_config()
    env_vars = load_env()
    
    print()
    print(color("┌─────────────────────────────────────────────────────────┐", Colors.CYAN))
    print(color("│               hermes-lite configuration                │", Colors.CYAN))
    print(color("└─────────────────────────────────────────────────────────┘", Colors.CYAN))
    
    # Paths
    print()
    print(color("◆ Paths", Colors.CYAN, Colors.BOLD))
    print(f"  Config:       {get_config_path()}")
    print(f"  Secrets:      {get_env_path()}")
    print(f"  Install:      {get_project_root()}")
    
    # API Keys
    print()
    print(color("◆ Runtime", Colors.CYAN, Colors.BOLD))
    
    keys = [
        ("ANTHROPIC_API_KEY", "Anthropic"),
        ("OPENAI_BASE_URL", "Local base URL"),
        ("OPENAI_API_KEY", "Local API key"),
    ]
    
    for env_key, name in keys:
        value = get_env_value(env_key)
        if env_key == "OPENAI_BASE_URL":
            display = value or color("(not set)", Colors.DIM)
        else:
            display = redact_key(value)
        print(f"  {name:<14} {display}")
    
    # Model settings
    print()
    print(color("◆ Model", Colors.CYAN, Colors.BOLD))
    model_config = config.get("model", {})
    if isinstance(model_config, dict):
        print(f"  Provider:     {model_config.get('provider', 'anthropic')}")
        print(f"  Model:        {model_config.get('default', 'not set')}")
    else:
        print("  Provider:     anthropic")
        print(f"  Model:        {model_config or 'not set'}")
    print(f"  Max turns:    {config.get('max_turns', 100)}")
    print(f"  Toolsets:     {', '.join(config.get('toolsets', ['all']))}")
    
    # Terminal
    print()
    print(color("◆ Terminal", Colors.CYAN, Colors.BOLD))
    terminal = config.get('terminal', {})
    print(f"  Backend:      {terminal.get('backend', 'local')}")
    print(f"  Working dir:  {terminal.get('cwd', '.')}")
    print(f"  Timeout:      {terminal.get('timeout', 60)}s")
    
    
    # Compression
    print()
    print(color("◆ Context Compression", Colors.CYAN, Colors.BOLD))
    compression = config.get('compression', {})
    enabled = compression.get('enabled', True)
    print(f"  Enabled:      {'yes' if enabled else 'no'}")
    if enabled:
        print(f"  Threshold:    {compression.get('threshold', 0.85) * 100:.0f}%")
        print(f"  Model:        {compression.get('summary_model', 'claude-haiku-4-5')}")

    print()
    print(color("─" * 60, Colors.DIM))
    print(color("  hermes-lite config edit     # Edit config file", Colors.DIM))
    print(color("  hermes-lite config set KEY VALUE", Colors.DIM))
    print(color("  hermes-lite setup           # Run setup wizard", Colors.DIM))
    print()


def edit_config():
    """Open config file in user's editor."""
    config_path = get_config_path()
    
    # Ensure config exists
    if not config_path.exists():
        save_config(DEFAULT_CONFIG)
        print(f"Created {config_path}")
    
    # Find editor
    editor = os.getenv('EDITOR') or os.getenv('VISUAL')
    
    if not editor:
        # Try common editors
        for cmd in ['nano', 'vim', 'vi', 'code', 'notepad']:
            import shutil
            if shutil.which(cmd):
                editor = cmd
                break
    
    if not editor:
        print(f"No editor found. Config file is at:")
        print(f"  {config_path}")
        return
    
    print(f"Opening {config_path} in {editor}...")
    subprocess.run([editor, str(config_path)])


def set_config_value(key: str, value: str):
    """Set a configuration value."""
    # Check if it's an API key (goes to .env)
    api_keys = [
        'ANTHROPIC_API_KEY',
        'OPENAI_API_KEY',
        'OPENAI_BASE_URL',
        'FAL_KEY',
        'SUDO_PASSWORD',
    ]

    if (key.upper() in api_keys
        or key.upper().endswith('_API_KEY')
        or key.upper().endswith('_TOKEN')
        or key.upper().endswith('_PASSWORD')
        or key.upper().startswith('TERMINAL_SSH')):
        save_env_value(key.upper(), value)
        print(f"✓ Set {key} in {get_env_path()}")
        return
    
    # Otherwise it goes to config.yaml
    # Read the raw user config (not merged with defaults) to avoid
    # dumping all default values back to the file
    config_path = get_config_path()
    user_config = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                user_config = yaml.safe_load(f) or {}
        except Exception:
            user_config = {}
    
    # Handle nested keys (e.g., "tts.provider")
    parts = key.split('.')
    current = user_config
    
    for part in parts[:-1]:
        if part not in current or not isinstance(current.get(part), dict):
            current[part] = {}
        current = current[part]
    
    # Convert value to appropriate type
    if value.lower() in ('true', 'yes', 'on'):
        value = True
    elif value.lower() in ('false', 'no', 'off'):
        value = False
    elif value.isdigit():
        value = int(value)
    elif value.replace('.', '', 1).isdigit():
        value = float(value)
    
    current[parts[-1]] = value
    
    # Write only user config back (not the full merged defaults)
    ensure_hermes_home()
    with open(config_path, 'w') as f:
        yaml.dump(user_config, f, default_flow_style=False, sort_keys=False)
    
    # Keep .env in sync for keys that terminal_tool reads directly from env vars.
    # config.yaml is authoritative, but terminal_tool only reads TERMINAL_ENV etc.
    _config_to_env_sync = {
        "terminal.backend": "TERMINAL_ENV",
        "terminal.docker_image": "TERMINAL_DOCKER_IMAGE",
        "terminal.singularity_image": "TERMINAL_SINGULARITY_IMAGE",
        "terminal.modal_image": "TERMINAL_MODAL_IMAGE",
        "terminal.daytona_image": "TERMINAL_DAYTONA_IMAGE",
        "terminal.cwd": "TERMINAL_CWD",
        "terminal.timeout": "TERMINAL_TIMEOUT",
    }
    if key in _config_to_env_sync:
        save_env_value(_config_to_env_sync[key], str(value))

    print(f"✓ Set {key} = {value} in {config_path}")


# =============================================================================
# Command handler
# =============================================================================

def config_command(args):
    """Handle config subcommands."""
    subcmd = getattr(args, 'config_command', None)
    
    if subcmd is None or subcmd == "show":
        show_config()
    
    elif subcmd == "edit":
        edit_config()
    
    elif subcmd == "set":
        key = getattr(args, 'key', None)
        value = getattr(args, 'value', None)
        if not key or not value:
            print("Usage: hermes config set KEY VALUE")
            print()
            print("Examples:")
            print("  hermes-lite config set model.default claude-sonnet-4-5-20250929")
            print("  hermes-lite config set terminal.backend local")
            print("  hermes-lite config set ANTHROPIC_API_KEY sk-ant-...")
            sys.exit(1)
        set_config_value(key, value)
    
    elif subcmd == "path":
        print(get_config_path())
    
    elif subcmd == "env-path":
        print(get_env_path())
    
    elif subcmd == "migrate":
        print()
        print(color("🔄 Checking configuration for updates...", Colors.CYAN, Colors.BOLD))
        print()
        
        # Check what's missing
        missing_env = get_missing_env_vars(required_only=False)
        missing_config = get_missing_config_fields()
        current_ver, latest_ver = check_config_version()
        
        if not missing_env and not missing_config and current_ver >= latest_ver:
            print(color("✓ Configuration is up to date!", Colors.GREEN))
            print()
            return
        
        # Show what needs to be updated
        if current_ver < latest_ver:
            print(f"  Config version: {current_ver} → {latest_ver}")
        
        if missing_config:
            print(f"\n  {len(missing_config)} new config option(s) will be added with defaults")
        
        required_missing = [v for v in missing_env if v.get("is_required")]
        optional_missing = [
            v for v in missing_env
            if not v.get("is_required") and not v.get("advanced")
        ]
        
        if required_missing:
            print(f"\n  ⚠️  {len(required_missing)} required API key(s) missing:")
            for var in required_missing:
                print(f"     • {var['name']}")
        
        if optional_missing:
            print(f"\n  ℹ️  {len(optional_missing)} optional API key(s) not configured:")
            for var in optional_missing:
                tools = var.get("tools", [])
                tools_str = f" (enables: {', '.join(tools[:2])})" if tools else ""
                print(f"     • {var['name']}{tools_str}")
        
        print()
        
        # Run migration
        results = migrate_config(interactive=True, quiet=False)
        
        print()
        if results["env_added"] or results["config_added"]:
            print(color("✓ Configuration updated!", Colors.GREEN))
        
        if results["warnings"]:
            print()
            for warning in results["warnings"]:
                print(color(f"  ⚠️  {warning}", Colors.YELLOW))
        
        print()
    
    elif subcmd == "check":
        # Non-interactive check for what's missing
        print()
        print(color("📋 Configuration Status", Colors.CYAN, Colors.BOLD))
        print()
        
        current_ver, latest_ver = check_config_version()
        if current_ver >= latest_ver:
            print(f"  Config version: {current_ver} ✓")
        else:
            print(color(f"  Config version: {current_ver} → {latest_ver} (update available)", Colors.YELLOW))
        
        print()
        print(color("  Required:", Colors.BOLD))
        for var_name in REQUIRED_ENV_VARS:
            if get_env_value(var_name):
                print(f"    ✓ {var_name}")
            else:
                print(color(f"    ✗ {var_name} (missing)", Colors.RED))
        
        print()
        print(color("  Optional:", Colors.BOLD))
        for var_name, info in OPTIONAL_ENV_VARS.items():
            if get_env_value(var_name):
                print(f"    ✓ {var_name}")
            else:
                tools = info.get("tools", [])
                tools_str = f" → {', '.join(tools[:2])}" if tools else ""
                print(color(f"    ○ {var_name}{tools_str}", Colors.DIM))
        
        missing_config = get_missing_config_fields()
        if missing_config:
            print()
            print(color(f"  {len(missing_config)} new config option(s) available", Colors.YELLOW))
            print(f"    Run 'hermes-lite config migrate' to add them")
        
        print()
    
    else:
        print(f"Unknown config command: {subcmd}")
        print()
        print("Available commands:")
        print("  hermes-lite config           Show current configuration")
        print("  hermes-lite config edit      Open config in editor")
        print("  hermes-lite config set K V   Set a config value")
        print("  hermes-lite config check     Check for missing/outdated config")
        print("  hermes-lite config migrate   Update config with new options")
        print("  hermes-lite config path      Show config file path")
        print("  hermes-lite config env-path  Show .env file path")
        sys.exit(1)

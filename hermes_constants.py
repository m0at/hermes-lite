"""Shared constants for hermes-lite."""

from pathlib import Path

ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_MODELS_URL = f"{ANTHROPIC_BASE_URL}/v1/models"
DEFAULT_HERMES_HOME = Path.home() / ".hermes-lite"

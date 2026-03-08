#!/usr/bin/env python3
"""
Utility functions for the demo application.
"""

import json
import os


def read_config(filepath):
    """Read configuration from a JSON file."""
    # TODO: Add error handling for missing files
    with open(filepath, 'r') as f:
        return json.load(f)


def write_config(filepath, data):
    """Write configuration to a JSON file."""
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)


def list_files(directory):
    """List all files in a directory."""
    # TODO: Add recursive option
    return [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]


def ensure_directory(path):
    """Ensure a directory exists."""
    os.makedirs(path, exist_ok=True)

#!/usr/bin/env python3
"""
Calculator module with basic arithmetic operations.

This file is designed to demonstrate the patch tool's fuzzy matching.
Try making changes even with whitespace differences!
"""


def add(a, b):
    """Add two numbers."""
    return a + b


def subtract(a, b):
    """Subtract b from a."""
    result = a - b
    return result


def divide(a, b):
    """Divide a by b."""
    # TODO: Add zero division handling
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


# TODO: Add multiply function
# TODO: Add power function
# TODO: Add modulo function

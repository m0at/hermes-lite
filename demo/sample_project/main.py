#!/usr/bin/env python3
"""
Demo application for hermes-lite showcase.

This file contains intentional TODOs and areas for improvement
to demonstrate the various tools and features.
"""

import sys
from calculator import add, subtract


def greet(name):
    """Greet a person by name."""
    # TODO: Add more personalized greetings
    return f"Hello, {name}!"


def process_numbers(a, b):
    """Process two numbers with various operations."""
    # TODO: Add error handling for invalid inputs
    result_add = add(a, b)
    result_sub = subtract(a, b)
    
    print(f"Addition: {a} + {b} = {result_add}")
    print(f"Subtraction: {a} - {b} = {result_sub}")
    # TODO: Add multiplication and division
    
    return result_add, result_sub


def main():
    """Main entry point."""
    print(greet("World"))
    
    # TODO: Add command-line argument parsing
    if len(sys.argv) > 2:
        a = int(sys.argv[1])
        b = int(sys.argv[2])
        process_numbers(a, b)
    else:
        print("Usage: main.py <num1> <num2>")
        process_numbers(10, 5)


if __name__ == "__main__":
    main()

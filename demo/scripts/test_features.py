#!/usr/bin/env python3
"""
Python test harness for demonstrating hermes-lite features.

This script can be used to programmatically test features or
as a reference for how to interact with the agent via the subprocess protocol.
"""

import json
import subprocess
import sys
import time
from pathlib import Path


class HermesDemo:
    """Demo harness for hermes-lite features."""
    
    def __init__(self, python_bin="python3"):
        self.python_bin = python_bin
        self.root_dir = Path(__file__).parent.parent.parent
        
    def run_single_shot(self, query, model=None):
        """Run a single-shot query and return the output."""
        cmd = [self.python_bin, "-m", "hermes_cli.main", "chat", "-q", query]
        if model:
            cmd.extend(["--model", model])
        
        print(f"🚀 Running: {query[:80]}...")
        result = subprocess.run(
            cmd,
            cwd=self.root_dir,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        return result.stdout, result.stderr, result.returncode
    
    def test_read_file(self):
        """Test the read_file tool."""
        print("\n📖 Testing read_file tool...")
        stdout, stderr, code = self.run_single_shot(
            "Read demo/sample_project/main.py and tell me what it does in one sentence"
        )
        
        success = code == 0 and "def " in stdout.lower()
        print(f"   {'✅' if success else '❌'} read_file: {code}")
        return success
    
    def test_search_files(self):
        """Test the search_files tool."""
        print("\n🔍 Testing search_files tool...")
        stdout, stderr, code = self.run_single_shot(
            "Search for all TODO comments in demo/ and count them"
        )
        
        success = code == 0 and "todo" in stdout.lower()
        print(f"   {'✅' if success else '❌'} search_files: {code}")
        return success
    
    def test_write_file(self):
        """Test the write_file tool."""
        print("\n✍️  Testing write_file tool...")
        stdout, stderr, code = self.run_single_shot(
            "Write 'Hello from hermes-lite demo!' to demo/test_output.txt"
        )
        
        # Check if file was created
        test_file = self.root_dir / "demo" / "test_output.txt"
        success = code == 0 and test_file.exists()
        
        if success:
            test_file.unlink()  # Clean up
        
        print(f"   {'✅' if success else '❌'} write_file: {code}")
        return success
    
    def test_terminal(self):
        """Test the terminal tool."""
        print("\n💻 Testing terminal tool...")
        stdout, stderr, code = self.run_single_shot(
            "Run 'echo Hello from terminal tool' and show me the output"
        )
        
        success = code == 0 and "hello" in stdout.lower()
        print(f"   {'✅' if success else '❌'} terminal: {code}")
        return success
    
    def test_patch(self):
        """Test the patch tool."""
        print("\n🔧 Testing patch tool...")
        
        # First, create a test file
        test_file = self.root_dir / "demo" / "patch_test.py"
        test_file.write_text("def old_function():\n    pass\n")
        
        stdout, stderr, code = self.run_single_shot(
            "Use patch to change 'old_function' to 'new_function' in demo/patch_test.py"
        )
        
        success = code == 0 and test_file.exists()
        if success:
            content = test_file.read_text()
            success = "new_function" in content
        
        if test_file.exists():
            test_file.unlink()  # Clean up
        
        print(f"   {'✅' if success else '❌'} patch: {code}")
        return success
    
    def test_todo(self):
        """Test the todo tool."""
        print("\n📋 Testing todo tool...")
        stdout, stderr, code = self.run_single_shot(
            "Create a todo list with 3 tasks: 1) Read files 2) Analyze code 3) Write report"
        )
        
        success = code == 0 and "todo" in stdout.lower()
        print(f"   {'✅' if success else '❌'} todo: {code}")
        return success
    
    def run_all_tests(self):
        """Run all feature tests."""
        print("🎯 hermes-lite Feature Test Suite")
        print("=" * 50)
        
        tests = [
            ("read_file", self.test_read_file),
            ("search_files", self.test_search_files),
            ("write_file", self.test_write_file),
            ("terminal", self.test_terminal),
            ("patch", self.test_patch),
            ("todo", self.test_todo),
        ]
        
        results = {}
        for name, test_func in tests:
            try:
                results[name] = test_func()
            except Exception as e:
                print(f"   ❌ {name}: Exception: {e}")
                results[name] = False
        
        # Summary
        print("\n" + "=" * 50)
        print("📊 Test Summary")
        print("=" * 50)
        
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        
        for name, success in results.items():
            print(f"   {'✅' if success else '❌'} {name}")
        
        print(f"\n   {passed}/{total} tests passed")
        
        return passed == total


def main():
    """Main entry point."""
    demo = HermesDemo()
    
    if len(sys.argv) > 1:
        # Run specific test
        test_name = sys.argv[1]
        if hasattr(demo, f"test_{test_name}"):
            getattr(demo, f"test_{test_name}")()
        else:
            print(f"Unknown test: {test_name}")
            print("Available tests: read_file, search_files, write_file, terminal, patch, todo")
            sys.exit(1)
    else:
        # Run all tests
        success = demo.run_all_tests()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

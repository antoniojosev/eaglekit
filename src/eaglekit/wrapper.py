#!/usr/bin/env python3
"""
Eagle Kit Shell Integration

This module provides shell function generation for seamless navigation.
"""

import os
import sys
from pathlib import Path


def generate_shell_function():
    """Generate shell function for direct navigation."""
    function = '''
# Eagle Kit shell integration function
ek() {
    # Special handling for 'cd' command with project name
    if [ "$1" = "cd" ] && [ -n "$2" ] && [ "$#" -eq 2 ]; then
        # Try to get project path using the Python CLI
        local project_path
        project_path=$(ek-core cd --path "$2" 2>/dev/null)
        
        # If successful and path exists, navigate directly
        if [ $? -eq 0 ] && [ -n "$project_path" ] && [ -d "$project_path" ]; then
            cd "$project_path" || return 1
            echo "📁 $2 → $project_path"
            return 0
        fi
    fi
    
    # For all other commands, delegate to the Python CLI
    command ek-core "$@"
}
'''
    return function.strip()


def main():
    """Main entry point that just delegates to ek-core for now."""
    if len(sys.argv) > 1 and sys.argv[1] == "--shell-function":
        print(generate_shell_function())
        return
    
    # For now, just delegate everything to ek-core
    # The shell function installation will be handled separately
    import subprocess
    sys.exit(subprocess.call(["ek-core"] + sys.argv[1:]))


if __name__ == "__main__":
    main()
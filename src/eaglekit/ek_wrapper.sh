#!/bin/bash
# Eagle Kit Shell Wrapper
# Enables direct navigation with 'ek cd project' while preserving all other functionality

# Function to handle Eagle Kit commands with direct navigation
ek_main() {
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
    exec ek-core "$@"
}

# Execute the main function with all arguments
ek_main "$@"
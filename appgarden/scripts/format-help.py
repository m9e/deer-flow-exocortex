#!/usr/bin/env python3
"""
Format help output for Makefile targets with proper coloring and argument parsing.
"""

import re
import sys


def format_help_line(target, description):
    """Format a single help line with proper coloring for command, args, and description."""
    # ANSI color codes
    RESET = "\033[0m"
    COMMENT = "\033[2m"  # Dim
    ARGS = "\033[0;36m"  # Cyan

    # Parse the description for usage patterns
    usage_match = re.match(r"^(.*?)\s*-\s*usage:\s*make\s+\S+\s*(.*)$", description)

    # Also check for inline argument patterns like "TYPE={app|tool} NAME={name}"
    args_in_desc = re.search(r"(TYPE=\{[^}]+\}\s*NAME=\{[^}]+\})", description)

    if usage_match:
        desc = usage_match.group(1).strip()
        args = usage_match.group(2).strip()

        if args:
            # Calculate total command+args length for alignment
            cmd_part = f"make {target} {args}"
            # Align description at column 60
            padding = max(1, 60 - len(cmd_part))
            return f"  make {target} {ARGS}{args}{RESET}{' ' * padding}{COMMENT}# {desc}{RESET}"
        else:
            cmd_part = f"make {target}"
            padding = max(1, 60 - len(cmd_part))
            return f"  make {target}{' ' * padding}{COMMENT}# {description}{RESET}"
    elif args_in_desc:
        # Extract args and clean description
        args = args_in_desc.group(1)
        desc = description.replace(args, "").strip()

        # Calculate total command+args length for alignment
        cmd_part = f"make {target} {args}"
        # Align description at column 60
        padding = max(1, 60 - len(cmd_part))
        return f"  make {target} {ARGS}{args}{RESET}{' ' * padding}{COMMENT}# {desc}{RESET}"
    else:
        # No usage pattern, just format normally
        cmd_part = f"make {target}"
        padding = max(1, 60 - len(cmd_part))
        return f"  make {target}{' ' * padding}{COMMENT}# {description}{RESET}"


def main():
    """Read targets and descriptions from stdin and format them."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        # Split on the delimiter (##)
        parts = line.split("##", 1)
        if len(parts) == 2:
            target = parts[0].strip()
            description = parts[1].strip()
            print(format_help_line(target, description))


if __name__ == "__main__":
    main()

"""CLI entrypoint for Stratum-4 deployment targets.

Usage:
    python -m src.platform.deployment --mode local
    python -m src.platform.deployment --mode container --config-file /path/to/config.yaml
"""

from __future__ import annotations

import sys


def main() -> None:
    """Parse CLI args and invoke the deployment target."""
    mode = "local"
    config_file = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--mode" and i + 1 < len(args):
            mode = args[i + 1]
            i += 2
        elif args[i] == "--config-file" and i + 1 < len(args):
            config_file = args[i + 1]
            i += 2
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            sys.exit(1)

    from src.platform.deployment import run_target

    run_target(mode=mode)


if __name__ == "__main__":
    main()

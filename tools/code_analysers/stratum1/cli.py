import argparse
import sys
from .runner import run_checks

def main():
    parser = argparse.ArgumentParser(description="Stratum 1 Invariant Checker")
    parser.add_argument("--root", default=".", help="Repo root")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--strict", action="store_true")

    args = parser.parse_args()
    result = run_checks(root=args.root, output_format=args.format, strict=args.strict)
    sys.exit(0 if result.ok else 1)

if __name__ == "__main__":
    main()
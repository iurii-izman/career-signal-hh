from __future__ import annotations

import argparse

from .cli_builders import build_all_parsers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="career-signal-hh")
    sub = parser.add_subparsers(dest="command", required=True)
    build_all_parsers(sub)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))

from __future__ import annotations

import argparse
import json
from pathlib import Path

from codemem.engine import CodeMemEngine
from codemem.mcp import serve_stdio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codemem")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Build repository memory")
    index_parser.add_argument("--repo", default=".", help="Repository root")

    query_parser = subparsers.add_parser("query", help="Query repository memory")
    query_parser.add_argument("--repo", default=".", help="Repository root")
    query_parser.add_argument("--prompt", required=True, help="Natural-language query")
    query_parser.add_argument("--limit", type=int, default=12)

    plan_parser = subparsers.add_parser("plan", help="Plan a change from repository memory")
    plan_parser.add_argument("--repo", default=".", help="Repository root")
    plan_parser.add_argument("--request", required=True, help="Requested change")
    plan_parser.add_argument("--limit", type=int, default=10)

    refresh_parser = subparsers.add_parser("refresh", help="Refresh repository memory")
    refresh_parser.add_argument("--repo", default=".", help="Repository root")

    dead_code_parser = subparsers.add_parser("dead-code", help="Find dead-code candidates")
    dead_code_parser.add_argument("--repo", default=".", help="Repository root")

    mcp_parser = subparsers.add_parser("serve-mcp", help="Run the stdio MCP server")
    mcp_parser.add_argument("--repo", default=".", help="Repository root")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    repo_root = Path(getattr(args, "repo", ".")).resolve()
    engine = CodeMemEngine(repo_root)

    if args.command == "index":
        _print(engine.index_repo().to_dict())
        return
    if args.command == "query":
        _print(engine.query_memory(args.prompt, limit=args.limit).to_dict())
        return
    if args.command == "plan":
        _print(engine.plan_change(args.request, limit=args.limit).to_dict())
        return
    if args.command == "refresh":
        _print(engine.refresh_memory().to_dict())
        return
    if args.command == "dead-code":
        _print(engine.find_dead_code())
        return
    if args.command == "serve-mcp":
        serve_stdio(repo_root)
        return
    parser.error(f"Unknown command: {args.command}")


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

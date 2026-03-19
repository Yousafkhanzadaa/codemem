# CodeMem

CodeMem is a local-first repository memory engine for coding agents.

Instead of forcing an LLM to rediscover a codebase from raw files on every request, CodeMem builds persistent repository memory: files, symbols, relationships, and a focused task packet for the current prompt. It exposes that memory through a CLI and a stdio MCP server.

## Why this exists

Most coding agents still work by repeatedly searching files, reading chunks, and hoping the prompt contains enough context. That degrades on larger repositories.

CodeMem takes a different approach:

- index the repository into memory
- retrieve only the smallest useful subgraph for the task
- explain why those entities were selected
- keep the memory local and refreshable after changes

The goal is not “more context.” The goal is better context.

## Current capabilities

CodeMem v0.2 supports:

- deterministic indexing for TypeScript, JavaScript, TSX, JSX, and Python files
- persistent local memory stored in `.codemem/repository_memory.json`, with a temp-cache fallback for read-only repositories
- entity extraction for files, functions, and classes
- relationship extraction for containment, exports, imports, and conservative call edges
- analyzer-driven indexing for JavaScript/TypeScript and Python
- hybrid retrieval with typo correction, synonym expansion, retrieval modes, snippets, graph-aware neighbor expansion, and focused packet compaction
- task packets with direct hits, primary focus files, deferred sibling matches, neighbors, coverage, confidence, reasoning, and relationship summaries
- lightweight impact analysis and change planning
- dead-code candidate discovery with evidence and confidence buckets
- a stdio MCP server for MCP-compatible clients

## Core ideas

CodeMem is built around a few rules:

- structural truth comes from parsing and static heuristics, not the LLM
- repository memory is local-first and refreshable
- retrieval should return a small validated slice, not the whole graph
- MCP is an adapter, not the product
- patch generation comes after memory quality and retrieval quality

## How it works

1. Index the repo into repository memory.
2. Classify the user’s intent from the prompt.
3. Normalize the query with typo correction and semantic expansion.
4. Rank relevant entities from memory.
5. Compact the results into the smallest useful set of primary files and symbols.
6. Expand a small graph neighborhood around that focused set.
7. Return a task packet with:
   - direct hits
   - focus files
   - deferred lower-priority matches
   - neighboring entities
   - relationships
   - coverage
   - confidence
   - retrieval reasoning

## Example use cases

Questions:

- “Where is subscription checkout implemented?”
- “What changes if I replace one-time purchases with subscriptions?”
- “Where is the image resize logic?”
- “Which files are most likely involved in auth?”

Planning:

- “Replace guest checkout with account-based checkout.”
- “Clean up unused crop helpers.”
- “Show the blast radius of changing the billing flow.”

## Project status

This is an early prototype.

What works:

- local indexing
- retrieval
- planning
- MCP exposure

What is not implemented yet:

- code patch generation
- code application and rollback
- runtime-aware validation
- per-language deep semantic analyzers
- multi-user/team memory

## Requirements

- Python 3.11+
- no external services required for the current local-first flow

## Quick start

Run from this repository:

```bash
cd /Users/[username]/personal_projects/codemem
```

Index a target repository:

```bash
PYTHONPATH=src python3 -m codemem index --repo /absolute/path/to/target-repo
```

Query repository memory:

```bash
PYTHONPATH=src python3 -m codemem query --repo /absolute/path/to/target-repo --prompt "where is the image resize logic?"
```

Plan a change:

```bash
PYTHONPATH=src python3 -m codemem plan --repo /absolute/path/to/target-repo --request "replace one-time purchases with subscriptions"
```

Refresh memory after code changes:

```bash
PYTHONPATH=src python3 -m codemem refresh --repo /absolute/path/to/target-repo
```

Run the MCP server over stdio:

```bash
PYTHONPATH=src python3 -m codemem serve-mcp --repo /absolute/path/to/target-repo
```

## CLI commands

- `index`: build repository memory for a repo
- `query`: retrieve a focused memory slice for a prompt
- `plan`: build a constrained change plan
- `refresh`: rebuild local memory
- `dead-code`: list low-confidence dead-code candidates
- `serve-mcp`: expose CodeMem through stdio MCP

## MCP tools

The current MCP server exposes:

- `memory.index_repo`
- `memory.query`
- `memory.impact_analysis`
- `memory.plan_change`
- `memory.get_entity`
- `memory.get_neighbors`
- `memory.find_dead_code`
- `memory.refresh`

## Repository layout

```text
src/codemem/
  cli.py        CLI entrypoint
  deadcode.py   dead-code analysis
  engine.py     high-level application surface
  indexer.py    analyzer-driven repository indexing
  intent.py     compatibility wrapper for retrieval
  mcp.py        stdio MCP adapter
  models.py     shared data models
  planner.py    change planning
  retrieval.py  hybrid retrieval pipeline
  store.py      local memory persistence
  analyzers/    language analyzers

tests/
  test_engine.py
  test_mcp.py
  support.py
```

## Verification

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Limitations

- retrieval is still heuristic
- call graph extraction is conservative and incomplete
- dynamic framework wiring is not deeply understood yet
- large polyglot monorepos will need language-specific adapters
- confidence is currently a retrieval heuristic, not a formal guarantee

## Next steps

Planned improvements:

- stronger task-specific retrieval modes
- richer focus-file summaries for downstream patch planners
- embedding-backed semantic retrieval
- safer patch planning and execution
- language/framework adapters beyond the current baseline

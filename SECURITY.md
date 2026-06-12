# Security Policy

## Threat Model

MingCang is a **local-first, single-user** research workbench. The security
posture follows from that:

- The SQLite database, `.env`, and project memory live on the user's own
  machine and are treated as a trusted local surface. The database is **not
  encrypted at rest by design** — protecting local files is delegated to
  OS-level controls (file permissions, full-disk encryption such as FileVault).
- Nothing is sent to a server operated by this project. Outbound traffic only
  goes to the data/LLM providers the user explicitly configures.
- The HTTP/MCP agent surface is for local use by default. Remote exposure is
  **opt-in** (`MINGCANG_AGENT_MODE=remote`), requires
  `MINGCANG_AGENT_API_KEY`, is read-only by default, and mutating actions
  additionally require an explicit allowlist
  (`MINGCANG_AGENT_REMOTE_WRITE_ENABLED` +
  `MINGCANG_AGENT_REMOTE_WRITE_ACTIONS`). See [AGENTS.md](AGENTS.md) for the
  full rules.
- Write paths default to dry-run; persistence requires `--confirm`.

## Supported Versions

This project is in active development and tracks the latest commit on the
default branch. Only the latest commit is supported for security fixes.

## Reporting a Vulnerability

If you believe you have found a security issue in MingCang, please **do not
open a public GitHub issue**.

Instead, report it privately through GitHub Security Advisories:

1. Go to <https://github.com/Zeeechenn/MingCang/security/advisories/new>
2. Fill in a short description and reproduction steps
3. Submit the advisory

The maintainer aims to respond within 7 days. After a fix is available, the
advisory will be published with credit to the reporter (unless anonymity is
requested).

## Scope

In scope:

- The Python backend in `backend/`
- The React frontend in `frontend/`
- The MCP server (`backend/agent/mcp_server.py`) and HTTP agent surface
- Remote agent authentication and write-allowlist behavior

Out of scope:

- Issues that require access to a user's local `.env`, local SQLite file,
  or local agent session — these are part of the trusted local development
  surface
- Findings against third-party data providers (Tushare, Tavily, Anspire,
  Eastmoney, AkShare, etc.); please report those upstream
- Findings against personal trading decisions or paper-trading results;
  MingCang does not place real orders and is not investment advice

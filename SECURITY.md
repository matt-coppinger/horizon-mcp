# Security Policy

## Reporting a Vulnerability

Please report security vulnerabilities privately using [GitHub's private vulnerability reporting](https://github.com/matt-coppinger/horizon-mcp/security/advisories/new) (Security tab → "Report a vulnerability") rather than opening a public issue.

Include:
- A description of the vulnerability and its potential impact
- Steps to reproduce (or a minimal proof of concept)
- The affected version/commit

This is a solo-maintained project — there's no SLA, but I'll acknowledge reports and aim to ship a fix or mitigation promptly for anything credible. You're welcome to open a normal issue for non-sensitive hardening suggestions.

## Supported Versions

This project does not yet have tagged releases; only the `main` branch is supported. Fixes land there and there is no backport policy.

## Scope Notes

A few things are by design rather than bugs, to save you a report:
- `HORIZON_VERIFY_SSL=false` intentionally disables TLS certificate verification — it's a documented opt-in for lab use, not a default.
- In the single-user modes (stdio, or HTTP with `MCP_API_KEY`) the server uses one Horizon session for all outbound Horizon API calls, and anyone who can use that instance has that session's full privileges. To share one HTTP server between people, use multi-user mode (`MCP_USERS_FILE`), where each API key has its own Horizon session and signs in with its own account — or run one instance per person. See the README's "Multi-user HTTP" and Security Notes sections. A way for one multi-user caller to reach another's Horizon session is in scope: please report it.
- Dependency vulnerabilities are tracked via [Dependabot alerts](https://github.com/matt-coppinger/horizon-mcp/security/dependabot) on this repo.

If you're unsure whether something is in scope, report it privately anyway and we'll sort it out.

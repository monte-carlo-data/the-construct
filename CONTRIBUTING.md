# Contributing

We welcome contributions — new agents, improvements to existing skills, better runbooks, bug fixes.

## Before You Start

- Open an issue to discuss new agents or significant changes before investing time in a PR
- Each agent should map to a recognizable security domain (CISSP, NIST CSF, or equivalent)
- New agents should follow the existing pattern: a skill file in `.claude/commands/` and a runbook in `docs/runbooks/agents/`

## Skill File Conventions

Skill files live in `.claude/commands/<agent-name>.md` and follow this frontmatter:

```yaml
---
name: <agent-name>
description: >
  One paragraph description of what the agent does and when to invoke it.
user-invocable: true
context: fork
allowed-tools:
  - Bash
  - Read
  # ... only tools the agent actually needs
---
```

Keep `allowed-tools` minimal — only list what the agent requires. Don't add tools "just in case."

## Runbook Conventions

Runbooks live in `docs/runbooks/agents/<agent-name>.md` and should cover:

- What the agent does
- How to invoke it (with examples)
- Systems accessed (table: system, purpose, auth method)
- Prerequisites
- Scope rules — especially for offensive or destructive agents
- Key workflows
- Secrets required
- Known limitations
- Routing (when to hand off to another agent)

## Scope Rules Are Non-Negotiable

Any agent that can take actions (file tickets, send Slack messages, modify resources) must include explicit scope confirmation steps. The pattern from `/neo` — print the target and require an explicit "yes" before acting — should be followed by any agent that touches external systems.

## Pull Request Process

1. Fork the repo and create a branch
2. Add or modify the skill file and runbook together — they ship as a pair
3. Test the skill manually in Claude Code
4. Open a PR with a clear description of what the agent does and why it's useful

## Code of Conduct

Be excellent to each other.

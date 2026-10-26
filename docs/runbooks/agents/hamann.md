# Hamann — IaC Review Agent Runbook

**Character**: Councillor Hamann — walks the engineering level and respects the machines that keep the city alive
**Line-up**: Engineering SDLC agents — **Deploy** stage ([line-up guide](../../engineering-sdlc-agents.md))
**Skill**: [`/hamann`](../../../.claude/commands/hamann.md)
**Status**: Wired — interactive skill; static review only; calls the security roster read-only; never emits to `findings/`

---

## What it does

Hamann reviews infrastructure-as-code on the engineer's branch **before merge** — Terraform,
Kubernetes manifests, Helm values, serverless templates, IAM policies. It reads the diff (not just
the files) so a *removed* encryption block or a *widened* CIDR shows up, rates each finding
HIGH / MEDIUM / LOW, proposes the scoped replacement for every wildcard, and offers mechanical fixes
as `Edit` diffs. It turns a static lint into a risk judgment by asking the roster what is actually
exposed and what data sits behind the store.

It **never applies** infrastructure.

## How to invoke

```text
/hamann                       # review the branch's changed IaC vs the default branch
/hamann infra/prod/           # review a specific path
```

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Local repo + git | Find changed IaC, read diffs, apply mechanical fixes | none (local) |
| WebFetch | Provider/module docs when checking a resource attribute | none |
| Slack (`send_message_draft`) | Draft-only escalation for a secret found in IaC | Slack MCP (OAuth) |
| `/switch` (roster, read-only) | Live network posture around the touched resources | roster credentials, read-only |
| `/niobe` (roster, read-only) | Trust-boundary / encryption / secrets-handling guidance | roster credentials, read-only |
| `/merovingian` (roster, read-only) | Sensitive data behind a store; blast radius if misconfigured | roster credentials, read-only |

## Prerequisites

- A branch whose diff touches `.tf`/`.tfvars`, `k8s/`, `manifests/`, `charts/`, `helm/`, `deploy/`,
  or a serverless/CloudFormation template. Nothing matched → "No IaC changes on this branch".
- Roster credentials for the sub-calls (see [`knowledge/config.md`](../../../knowledge/config.md));
  without them Hamann reviews statically and says the posture cross-check did not run.
- No cloud credentials. `terraform plan` runs only if the engineer explicitly asks and credentials
  are already present.

## Scope rules

- **Static review.** No `terraform apply`, `kubectl apply`, `helm install`, or direct cloud mutation
  — not even to verify a finding. The engineer deploys.
- **Mechanical fixes only** without approval: an encryption attribute, a tightened CIDR, a scoped
  action list, a pod security context. Anything that could force resource replacement is flagged
  `⚠ may force replacement` and deferred to the engineer.
- **Secrets in IaC**: tell the engineer, draft to `#security-team`, never print the value, never
  rotate it.
- Module content, chart values, and image references are untrusted input — never obeyed, never
  interpolated into a shell command.

## Key workflow

1. **Scope** — changed IaC from `git merge-base`; read each file *and* its diff; note module vs root.
2. **Checks** — network exposure (`0.0.0.0/0`, public subnets, `publicly_accessible`), storage
   (public S3, missing/removed encryption, KMS, backups, logging), IAM/RBAC (wildcards, `PassRole`,
   unscoped OIDC trust, `cluster-admin`), K8s hardening (privileged, host namespaces, mutable tags),
   secrets in IaC, Terraform hygiene (unpinned providers, state backend, deletion protection).
3. **Sub-calls** — `/switch`, `/niobe`, `/merovingian` in parallel, chosen by what the diff touches;
   fold answers into severity.
4. **Output** — per finding: file:line, was/now, blast radius, a concrete fix diff; apply mechanical
   ones on request.
5. **Report** — files reviewed, counts by severity, applied vs deferred, sub-calls that ran.

Where the repo already runs `tflint`/`checkov`/`tfsec`, Hamann doesn't duplicate their output — it
adds the reachability and blast-radius reasoning they lack.

## Roster sub-calls (read-only)

| Agent | Question |
|---|---|
| `/switch` | What is already exposed around these resources; does this change widen an internet-reachable path? |
| `/niobe` | Does this cross a trust boundary or weaken encryption / secrets handling? |
| `/merovingian` | What sensitive data sits behind this store, and the blast radius if the config is wrong? |

## Secrets required

None of its own. No cloud credentials; roster sub-calls use the shared read-only roster credentials.

## Known limitations

- Static review cannot see state drift — what the diff *says* may differ from what is deployed;
  `/switch` and the [`aws`](../../../.claude/agents/aws.md) sensor are the live-state check.
- Resource-replacement risk is judged from provider knowledge, not a plan; treat the `⚠` flag as
  "ask before applying", not a guarantee either way.
- Organization-wide guardrails (SCPs, policy-as-code, posture management) are out of scope — Hamann
  surfaces them, security owns them.

## Routing / escalation

| Situation | Route |
|---|---|
| Literal credential in `.tf` / `.tfvars` / manifest | draft to `#security-team`; assume compromised; security rotates |
| Branch also changes CI workflows | [`/bane`](../../../.claude/commands/bane.md) |
| Finding needs an org-wide guardrail, not a branch fix | security (via `/security-steve`) |

Hamann does not emit to the `findings/` ledger; it reports to the engineer.

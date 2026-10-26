# Org Configuration

Fill in the values below before running any agents. Each agent reads from this file
to scope its queries to your organization.

---

## Core

```
YOUR_GITHUB_ORG=your-org-name          # e.g. acme-corp
YOUR_DOMAIN=your-domain.com            # primary external domain Oracle scans
YOUR_SECONDARY_DOMAINS=                # comma-separated, e.g. internal.io,api.yourco.com
YOUR_SECURITY_CHANNEL=#security-team   # Slack channel agents draft escalations to and post digests in
YOUR_HELPDESK_CHANNEL=#security-helpdesk  # where employees ask security questions
YOUR_ORG_NAME=Your Company Name        # used in Shodan/Censys org queries
```

## Credentials

Agents load secrets from a credential manager. Set your vault/tool name here:

```
YOUR_CREDENTIAL_VAULT=your-vault-name  # 1Password vault, AWS Secrets Manager path, etc.
YOUR_CREDENTIAL_TOOL=op                # op (1Password CLI), aws, vault, etc.
```

Credential item names expected by each agent (every value is a placeholder — the agents never print a secret):

| Agent | Secret | Item Name in Vault |
|---|---|---|
| Neo | `ANTHROPIC_API_KEY` | your-anthropic-key-item |
| Neo | `PENTAGI_API_TOKEN` | your-pentagi-token-item |
| Tank, Cypher, Apoc | `AIKIDO_CLIENT_ID` | your-aikido-client-id-item |
| Tank, Cypher, Apoc | `AIKIDO_CLIENT_SECRET` | your-aikido-client-secret-item |
| Cypher, Tank, Dozer | `SOCKET_API_TOKEN` | your-socket-token-item |
| Analyst, `panther` sensor | `PANTHER_API_TOKEN` | your-panther-token-item (read-only role) |
| Oracle, `wing` sensor | `WING_API_KEY` | your-wing-key-item |
| Merovingian, `bedrock` sensor | `BEDROCK_API_KEY` | your-bedrock-key-item |
| `aws` sensor, Switch, Niobe, Skidbladnir | AWS read-only role | your-readonly-role-profile (assume via SSO or a profile; never static keys) |
| Skidbladnir | `SPACELIFT_API_KEY_ID` / `SPACELIFT_API_KEY_SECRET` | your-spacelift-readonly-key-item |
| Trainman | AWS Cost Explorer read role | your-cost-explorer-profile |
| On-Call | `PAGERDUTY_API_TOKEN` (or your pager's equivalent) | your-pager-token-item |

## Inventory sources (Oracle)

Oracle reads your approved inventories from Git rather than a wiki, so the lists are reviewable and diff-able:

```
YOUR_APPROVED_AI_VENDORS_PATH=knowledge/approved-ai-vendors.md   # file in this repo (or a path in another repo)
YOUR_APPROVED_APPS_PATH=knowledge/Centralized_Internal_Applications.md
YOUR_INVENTORY_READER_APP=                                       # optional: GitHub App slug Oracle uses to read other repos
```

## Notion (optional)

```
YOUR_NOTION_WORKSPACE=your-workspace   # Notion workspace slug for internal URLs
YOUR_SECURITY_REVIEW_PROCESS_URL=      # Notion URL for your security review process doc
```

## Linear

Agents file tickets into a security team queue. Set your team and queue here:

```
YOUR_LINEAR_SECURITY_TEAM=Security     # Linear team name
YOUR_LINEAR_TRIAGE_STATE=Triage        # Default state for new tickets
YOUR_AGENT_TRACKING_PROJECT=           # Optional project agents file their own follow-ups into
```

## Repos the agents write to (always via PR, never to main)

```
YOUR_IAC_REPO=your-org/infrastructure          # Skidbladnir, Trainman, Hamann draft PRs here
YOUR_RISK_REGISTER_REPO=your-org/risk-register # Keymaker records treatment decisions here
YOUR_DETECTIONS_REPO=your-org/detections       # Analyst proposes false-positive filters here
```

## Headless runtime (optional)

The Concierge, Analyst, and On-Call can run from a queue in a read-only container. If you deploy them that way:

```
YOUR_REQUEST_QUEUE_URL=                # queue the Concierge polls for requests
YOUR_DETECTION_QUEUE_URL=              # queue the Analyst consumes fired detections from
YOUR_DISPATCH_TARGETS=tank,trinity,seraph   # roster agents registered as consult targets
```

## Optional Scanning

```
SHODAN_API_KEY=                        # Required for Oracle passive exposure scan
CENSYS_API_ID=                         # Required for Oracle Censys scan
CENSYS_API_SECRET=                     # Required for Oracle Censys scan
```

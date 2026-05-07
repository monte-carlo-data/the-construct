# Org Configuration

Fill in the values below before running any agents. Each agent reads from this file
to scope its queries to your organization.

---

## Core

```
YOUR_GITHUB_ORG=your-org-name          # e.g. acme-corp
YOUR_DOMAIN=your-domain.com            # primary external domain Oracle scans
YOUR_SECONDARY_DOMAINS=                # comma-separated, e.g. internal.io,api.yourco.com
YOUR_SECURITY_CHANNEL=#security        # Slack channel agents post digests to
YOUR_ORG_NAME=Your Company Name        # used in Shodan/Censys org queries
```

## Credentials

Agents load secrets from a credential manager. Set your vault/tool name here:

```
YOUR_CREDENTIAL_VAULT=your-vault-name  # 1Password vault, AWS Secrets Manager path, etc.
YOUR_CREDENTIAL_TOOL=op                # op (1Password CLI), aws, vault, etc.
```

Credential item names expected by each agent:

| Agent | Secret | Item Name in Vault |
|---|---|---|
| Neo | `ANTHROPIC_API_KEY` | your-anthropic-key-item |
| Neo | `PENTAGI_API_TOKEN` | your-pentagi-token-item |
| Tank | `AIKIDO_CLIENT_ID` | your-aikido-client-id-item |
| Tank | `AIKIDO_CLIENT_SECRET` | your-aikido-client-secret-item |

## Notion

```
YOUR_NOTION_WORKSPACE=your-workspace   # Notion workspace slug for internal URLs
YOUR_APPROVED_AI_VENDORS_URL=          # Notion URL for your approved AI vendor list
YOUR_SECURITY_REVIEW_PROCESS_URL=      # Notion URL for your security review process doc
```

## Linear

Agents file tickets into a security team queue. Set your team and queue here:

```
YOUR_LINEAR_SECURITY_TEAM=Security     # Linear team name
YOUR_LINEAR_TRIAGE_STATE=Triage        # Default state for new tickets
```

## Optional Scanning

```
SHODAN_API_KEY=                        # Required for Oracle passive exposure scan
CENSYS_API_ID=                         # Required for Oracle Censys scan
CENSYS_API_SECRET=                     # Required for Oracle Censys scan
```

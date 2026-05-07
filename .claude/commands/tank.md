---
name: tank
description: >
  Tank — Vulnerability triage agent for Monte Carlo. Named after Tank from The Matrix: born
  free, no implants, pure operator. "I'm the operator. I load the guns." Investigates a
  specific Aikido or Wiz finding, or a Linear vuln ticket, determines if it is a real
  vulnerability or a false positive, and takes the appropriate action: suppress in Aikido +
  close the ticket, or draft a fix. Use when: "triage this vuln", "is SEC-XXXX a false
  positive?", "look at this Aikido finding", "look at this Wiz finding", "should we fix or
  suppress this?". Accepts a Linear ticket ID, Aikido finding URL, or Wiz issue URL.
---

# Tank — Vulnerability Investigation & Disposition

Tank is the operator. He doesn't find the vulns — he loads them into the system, tracks them,
and makes sure nothing slips through. This skill investigates a single Aikido or Wiz finding,
or a Linear vulnerability ticket, reads the actual source code or cloud context, and makes a
disposition decision:
**false positive** (suppress + close) or **real vulnerability** (summarize fix path and hand off).

---

## Step 0 — Identify the target

The user will provide one of:

- A Linear ticket ID (e.g. `SEC-1395`)
- An Aikido finding URL (e.g. `https://app.aikido.dev/repositories/419303?sidebarIssue=2216811`)
- A Wiz issue URL (e.g. `https://app.wiz.io/issues#~(issue~'16ff94e9-5b21-44cc-9dde-d30dcd793ef5)`)
- A freeform description ("the yaml.load finding in common")

If a Linear ticket ID is given, fetch it with `mcp__linear__get_issue` to extract:

- The source URL from the description — Aikido or Wiz
- The affected file path and repo
- The rule/type of finding

**If the source URL is a Wiz link** (`app.wiz.io`), extract the issue ID from the `issue~'` fragment
and skip to **Step 1c** (Wiz path). Do not attempt to look it up in Aikido.

**If the source URL is an Aikido link** (`app.aikido.dev`), proceed with Step 1 (Aikido path).

If a Wiz URL is given directly, extract the issue ID and go to Step 1c.

If an Aikido URL is given, extract the finding ID from the `sidebarIssue=` query parameter.
Aikido URLs come in several formats — all yield the same finding ID:

- `https://app.aikido.dev/repositories/419303?sidebarIssue=2216811` (SAST/SCA, repo-scoped)
- `https://app.aikido.dev/queue?sidebarIssue=2216811` (global queue — may not work in UI)
- `https://app.aikido.dev/infrastructure/{cloud_id}/virtual-machines/{vm_id}?sidebarIssue=...` (VM/cloud_instance)
- `https://app.aikido.dev/cloud/{cloud_id}?sidebarIssue=...` (cloud misconfiguration)

Do **not** try to extract `code_repo_id` from the URL — always look it up from the export
API response instead (it may be null for cloud/VM findings).

After fetching the finding from the API, **construct the correct deep-link URL** using the
`group_id` (not the issue `id`) in the `sidebarIssue` param:

| `attack_surface` | URL pattern |
| --- | --- |
| `backend` / `code` (SAST/SCA) | `https://app.aikido.dev/repositories/{code_repo_id}?sidebarIssue={group_id}` |
| `cloud` (Lambda, S3, etc.) | `https://app.aikido.dev/cloud/{cloud_id}?sidebarIssue={group_id}` |
| `cloud_instance` (EC2/VM) | `https://app.aikido.dev/queue?sidebarIssue={group_id}` |
| `docker_container` | `https://app.aikido.dev/containers/{container_repo_id}?sidebarIssue={group_id}` |
| fallback | `https://app.aikido.dev/queue?sidebarIssue={group_id}` |

**Important:** Always use `group_id` (not `id`) in `sidebarIssue` — using the issue `id` causes
"Issue group not found" errors in the Aikido UI.

Use this URL when commenting on Linear tickets so the link is navigable.

If neither, ask the user to provide a ticket ID or Aikido URL before proceeding.

---

## Step 1 — Fetch the finding details from Aikido

Call the Aikido export API to get full finding metadata:

```text
GET https://app.aikido.dev/api/public/v1/issues/export
  ?format=json
  &filter_status=open
  &filter_severities=critical,high,medium,low
```

Authenticate with `AIKIDO_CLIENT_ID` / `AIKIDO_CLIENT_SECRET` (OAuth client credentials).
Fetch from 1Password — search for an item tagged or named "Aikido" with `client_id`/`client_secret`
fields in the your-credentials-vault:

```bash
AIKIDO_CLIENT_ID=$(op item get --vault "your-credentials-vault" "Agent: Aikido" --fields username)
AIKIDO_CLIENT_SECRET=$(op item get --vault "your-credentials-vault" "Agent: Aikido" --fields credential --reveal)
```

If the item name has changed, run `op item list --vault "your-credentials-vault" | grep -i aikido` to find
the current one. Use whichever item has valid `username` + `credential` fields.

Find the matching finding by ID. Extract:

- `id` — finding ID
- `group_id` — needed for suppression
- `code_repo_id` — repo ID
- `code_repo_name` — repo name
- `affected_file` — file path within the repo
- `rule` / `type` — what Aikido flagged
- `start_line` / `end_line` — location in file

---

## Step 1b — Check EC2 instance state (cloud_instance findings only)

If `attack_surface == "cloud_instance"` and a `virtual_machine_name` is present, check
whether the EC2 instance is running before triaging:

```bash
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values={virtual_machine_name}" \
  --query 'Reservations[].Instances[].{ID:InstanceId,State:State.Name,Team:Tags[?Key==`team`]|[0].Value}' \
  --output table
```

Try multiple AWS profiles if needed (`aws configure list-profiles`).

- **stopped / terminated** — the instance is not running. Aikido may still surface findings
  from its last scan. Suppress the finding in Aikido (it poses no active risk) and close
  the Linear ticket with a note that the instance is stopped. Also note if the `team` tag
  is missing and ask the instance owner to tag it before restarting.
- **running** — proceed with normal triage below.

---

## Step 1c — Fetch the finding details from Wiz (Wiz path only)

If the source is a Wiz URL, authenticate to the Wiz MCP server using `mcp__wiz__authenticate`
if not already authenticated. Then use available Wiz MCP tools to fetch the issue by ID.

Extract:

- Issue ID and title
- Severity (Critical / High / Medium / Low)
- Finding type (vulnerability, misconfiguration, secret, etc.)
- Affected resource: type, name, cloud account, region
- Affected packages or CVEs (for container/VM findings)
- Status (open, in progress, resolved)
- Any linked projects or subscriptions

For **container image findings** (e.g. `docker.io/montecarlodata/pre-release-agent`):

- List all CVEs or packages flagged by Wiz and note whether a fixed version is available for each
- **Cross-check Aikido** for the same container image — fetch open Aikido findings filtered to
  the `container_repo_name` and compare CVE lists. The two scanners regularly find different
  CVEs on the same image; you need both for a complete picture. Note which CVEs are in Wiz only,
  Aikido only, or both.
- Then proceed to **Step 1d** to run a first-party wizcli scan to confirm findings before
  making a true/false positive determination.

For **non-container Wiz findings** (cloud misconfigurations, IAM, secrets): proceed directly
to Step 3 (Analysis) — skip Steps 1d, 2, 2b, and 2c. Disposition options are **resolve in
Wiz** (mark as resolved or accepted risk) or **keep open and route to owner**.

**Wiz disposition actions (non-container):**

- **Accepted risk / false positive:** Use Wiz MCP to mark the issue as accepted risk with a
  rationale. Comment on the Linear ticket and close it (Done or Canceled as appropriate).

- **Real finding:** Check system ownership in `mc-knowledge/System_Ownership.md`, comment on
  the Linear ticket with CVE list, fix path, and recommended owner, and move ticket to Todo.

---

## Step 1d — wizcli container scan (container image findings only)

Run a first-party wizcli scan against the container image to independently confirm the CVEs
reported by Wiz and/or Aikido. This is the true positive / false positive gate for container
findings — do not make a disposition without it.

### Prerequisites

Check wizcli is installed and at v1.x:

```bash
wizcli version
```

If missing or v0.x, use `mcp__wiz__wizcli_setup` to install/upgrade first.

### Pull and scan the image

```bash
# Pull the image (use the exact digest from the Wiz finding for reproducibility)
docker pull {image_name}@{digest}

# Scan it — output JSON for programmatic parsing
wizcli scan container-image {image_name}@{digest} \
  --stdout=json --json-output-file /tmp/wizcli-scan.json

# Extract HIGH+ findings with CVE IDs and fix versions
cat /tmp/wizcli-scan.json | python3 -c "
import sys, json
data = json.load(sys.stdin)
findings = data.get('result', {}).get('vulnerabilities', []) or data.get('vulnerabilities', [])
high_plus = [f for f in findings if f.get('severity','').upper() in ('CRITICAL','HIGH')]
for f in sorted(high_plus, key=lambda x: x.get('severity','')):
    print(f\"{f.get('cveId','?')} | {f.get('name','?')} {f.get('version','?')} -> {f.get('fixedVersion','no fix')} | {f.get('severity','?')}\")
print(f'Total HIGH+: {len(high_plus)}')
"
```

### Parse the scan output

The wizcli JSON result stores vulnerable artifacts under
`result.vulnerableSBOMArtifactsByNameVersion` — NOT `result.vulnerabilities` (which is null).
Use this parser:

```bash
cat /tmp/wizcli-scan.json | python3 -c "
import sys, json
data = json.load(sys.stdin)
artifacts = data['result']['vulnerableSBOMArtifactsByNameVersion']
seen = set()
rows = []
for a in artifacts:
    name = a.get('name','')
    ver = a.get('version','')
    vf = a.get('vulnerabilityFindings', {})
    sev = vf.get('severities', {})
    crit = sev.get('criticalCount', 0)
    high = sev.get('highCount', 0)
    if crit == 0 and high == 0:
        continue
    fix = vf.get('fixedVersion') or 'no fix'
    rem = (vf.get('remediation') or '')[:60]
    label = a.get('type', {}).get('codeLibraryLanguage') or a.get('type', {}).get('group','?')
    key = (name, ver)
    if key in seen: continue
    seen.add(key)
    rows.append((crit, high, name, ver, fix, label, rem))
rows.sort(key=lambda x: (-x[0], -x[1]))
for crit, high, name, ver, fix, label, rem in rows:
    print(f'CRIT:{crit} HIGH:{high} | {label:12} | {name} {ver} -> {fix}')
    if rem: print(f'  fix: {rem}')
"
```

### Scanner cross-check

- **Confirmed by wizcli** → package is present and vulnerable. Proceed to Step 1e for reachability.
- **In Wiz/Aikido but NOT wizcli** → potential false positive or patched in a layer wizcli sees differently. Note the discrepancy — do not suppress without understanding why.
- **In wizcli but not Wiz/Aikido** → net-new finding, add to the ticket.

After building the confirmed package list, proceed to **Step 1e** (reachability analysis)
before making any true/false positive determination.

---

## Step 1e — Code reachability analysis (container image findings only)

Being present in the image ≠ exploitable. For each confirmed HIGH+ package, determine
whether the CVE's attack vector is actually reachable given how the package is used in
the application. Do not call something a true positive until this step is complete.

### 1. Find the source repo

The container image is built from a GitHub repo. Identify it by:

- The `code_repo_name` field from Aikido (e.g. `apollo-agent`)
- The image name (e.g. `pre-release-agent` → repo `apollo-agent`)
- If unclear, search: `gh repo list monte-carlo-data --json name | grep -i agent`

### 2. Read requirements files to classify direct vs transitive

```bash
# Read the pinned lockfile
gh api repos/monte-carlo-data/{repo}/contents/requirements.txt --jq '.content' | base64 -d

# Read the direct deps list
gh api repos/monte-carlo-data/{repo}/contents/requirements.in --jq '.content' | base64 -d 2>/dev/null
```

For each vulnerable package, note:

- **Direct dep** (appears in `requirements.in`) — app explicitly depends on it
- **Transitive dep** (only in `requirements.txt` with `# via` annotation) — pulled in by another package
- **Which package pulls it in** (from the `# via` comment)

### 3. Check installed version vs pinned version

Version drift between what's pinned and what's installed is a red flag — it means
the dep constraint isn't working and the image may be running a different version
than the team thinks.

```bash
docker run --rm --entrypoint /bin/sh {image_name}@{digest} \
  -c "/app/.venv/bin/pip show {package1} {package2} {package3} 2>/dev/null | grep -E 'Name:|Version:'"
```

If the installed version differs from the pinned version, note it explicitly — this is
a separate finding (broken pin) beyond just the CVE.

### 4. Find usage files for each direct dep

For each package that is a **direct dep**, find where it's imported in the repo:

```bash
# Get all Python files
gh api "repos/monte-carlo-data/{repo}/git/trees/main?recursive=1" \
  --jq '[.tree[] | select(.path | test("\\.py$")) | .path]' > /tmp/py_files.json

# For each file, check for imports of the vulnerable package
# Read the file content via gh api and grep for import statements
```

For each file that imports the package, read it:

```bash
gh api repos/monte-carlo-data/{repo}/contents/{file_path} --jq '.content' | base64 -d
```

Focus on: what functions/methods are called, what data flows into them, whether
that data is attacker-controlled or operator-controlled.

### 5. Cross-reference CVE attack vector against actual usage

For each package, answer these questions:

**What does the CVE require to trigger?**

- Network input (e.g. TLS handshake, HTTP request)
- Malicious file/data parsed by the library
- Specific function called (e.g. `jwt.decode()`, `yaml.load()`)
- Local access only

**Does the application code exercise that path?**

- If the CVE is in JWT *verification* but the code only calls `jwt.encode()` → NOT EXPLOITABLE
- If the CVE is in TLS handling and the package establishes TLS to customer infrastructure → EXPLOITABLE
- If the package is transitive and never directly called → EXPLOITABILITY UNCLEAR (treat as low)
- If input to the vulnerable function comes from operator credentials → LOW exploitability
- If input comes from end-user or external network traffic → HIGH exploitability

### 6. Output reachability verdict per package

For each HIGH+ package, produce:

```text
{package} {version} — CVE-XXXX
  Direct/Transitive: [direct | transitive via {parent}]
  Installed vs pinned: {installed_ver} vs {pinned_ver} [DRIFT DETECTED if different]
  CVE attack vector: [what the CVE requires]
  Usage in {repo}: [what function is called, in which file]
  Input source: [operator credentials | internal | user-controlled | external network]
  Verdict: EXPLOITABLE | NOT EXPLOITABLE | LOW EXPLOITABILITY | TRANSITIVE ONLY
  Priority: High | Medium | Low (routine bump)
```

### 7. Final true/false positive determination

- **EXPLOITABLE** → TRUE POSITIVE — patch urgently, note in ticket
- **NOT EXPLOITABLE as used** → CONTEXTUAL FALSE POSITIVE — still patch (routine dep bump)
  but do not treat as an active security risk; downgrade priority
- **LOW EXPLOITABILITY** → TRUE POSITIVE (lower priority) — patch in next sprint
- **TRANSITIVE ONLY / no direct call path** → LOW PRIORITY — patch as part of base image rebuild

After completing reachability for all packages, proceed to Step 3 (Analysis) with the
full reachability-annotated finding list.

---

## Step 2 — Read the source code (SAST/SCA findings only)

**Skip this step** if the finding has no `code_repo_name` or `affected_file` — this happens
for cloud findings (obsolete Lambda runtimes, misconfigured resources) and non-container
VM findings. For those, proceed directly to Step 3 using the metadata from the export API.

**Container image findings** skip this step too — they are handled by Steps 1c and 1d
(Wiz + Aikido cross-check and wizcli first-party scan). Do not send container findings
to Step 2.

For SAST/SCA findings with source code, use the GitHub API or `gh` CLI:

```bash
gh api repos/monte-carlo-data/{repo_name}/contents/{affected_file} --jq '.content' | base64 -d
```

Focus on the lines around `start_line`–`end_line` (±20 lines for context).

---

## Step 2b — Cross-check EOL findings against endoflife.date

If `type == "eol"`, cross-check before deciding — Aikido sometimes flags runtimes before
they are actually EOL.

```bash
curl -s "https://endoflife.date/api/aws-lambda.json" | jq '.[] | select(.cycle == "java11")'
```

Use product slug `aws-lambda` for Lambda runtimes, `nodejs` / `python` / `ubuntu` for VM packages.

- `eol` is a future date → not yet EOL, downgrade urgency
- `eol` is a past date → confirmed EOL, treat as real vulnerability

Include `https://endoflife.date/{product}` and the actual EOL date in your Linear comment.

---

## Step 2c — Find the true author (SAST findings only)

Before attributing the finding to any engineer or drafting any outreach, identify who
actually *introduced* the flagged line — not just who last touched the file.

**Never ping someone based solely on `git blame` output without verifying the flagged
line appears as an addition (`+`) in that commit's diff.** Monorepo migrations, mass
renames, and reformatting commits silently reset blame to the wrong person.

### Process

1. **Run `git blame`** on the flagged line to get the most recent commit SHA and author.

1. **Verify the commit actually introduced the line** — check whether the flagged line
   appears as an addition (`+`) in that commit's diff:

```bash
gh api repos/monte-carlo-data/{repo}/commits/{sha} \
  --jq '.files[] | select(.filename | test("{affected_file}")) | .patch' \
  | grep -n "^+" | grep "{flagged_pattern}"
```

1. **If the line is NOT a `+` in that diff** — the commit is a pass-through (migration,
   rename, reformat). Walk back through **all** commits on that file and collect every
   commit that added the flagged pattern — the **oldest match is the true origin**:

```bash
# Collect ALL commits that introduced the flagged pattern across all pages (do NOT break on first match)
for page in 1 2 3 4 5; do
  shas=$(gh api "repos/monte-carlo-data/{repo}/commits?path={affected_file}&per_page=50&page=$page" \
    --jq '.[].sha' 2>/dev/null)
  [ -z "$shas" ] && break
  while IFS= read -r sha; do
    patch=$(gh api "repos/monte-carlo-data/{repo}/commits/$sha" \
      --jq '.files[]? | select(.filename | test("{affected_file}")) | .patch // ""' 2>/dev/null)
    if echo "$patch" | grep -q "^+.*{flagged_pattern}"; then
      gh api "repos/monte-carlo-data/{repo}/commits/$sha" \
        --jq '{sha: .sha[0:8], author: .commit.author.name, email: .commit.author.email, date: .commit.author.date, message: .commit.message | split("\n")[0]}'
      gh api "repos/monte-carlo-data/{repo}/commits/$sha/pulls" \
        --jq '.[0] | "PR #\(.number): \(.title) — https://github.com/monte-carlo-data/{repo}/pull/\(.number)"' 2>/dev/null
      echo "---"
    fi
  done <<< "$shas"
done
```

The list is ordered newest-first across pages, so the **last entry printed is the original author**.
A line can appear as `+` in multiple commits if it was later edited — always use the
oldest (last printed) as the true origin.

1. **Pass-through commit red flags** — do not attribute to this person if any apply:
   - Commit message contains: "migration", "monorepo", "mv", "rename", "reformat", "move", "restructure"
   - The commit touches >10 files
   - The commit is authored by a bot or CI user

1. **Record the true author** — name, email, introducing commit SHA, and PR link.
   Always verify the PR link resolves before surfacing it to the user.

---

## Step 3 — Analyze the finding

Read the code and determine:

### False positive indicators

- The flagged pattern is safe by construction (e.g. `yaml.load()` with a `SafeLoader`-based
  custom `Loader`, parameterized queries that look like concatenation, test-only code paths)
- The finding is in a dev/test/fixtures path with no production equivalent
- The input to the flagged function is fully internal / not attacker-controlled

### Real vulnerability indicators

- User-controlled input reaches the flagged sink without sanitization
- The flagged pattern matches the rule description faithfully
- The code path is reachable from a production entry point

State your conclusion clearly:

- **FALSE POSITIVE** — explain why in 2-3 sentences
- **REAL VULNERABILITY** — describe the attack vector and blast radius

---

## Step 4 — Take action

### If FALSE POSITIVE

1. **Suppress in Aikido** — call the ignore endpoint using the `group_id`:

```text
PUT https://app.aikido.dev/api/public/v1/issues/groups/{group_id}/ignore
Authorization: Bearer {token}
Content-Type: application/json

{
  "reason": "<concise explanation, e.g. '_SecretTagLoader extends yaml.SafeLoader — no RCE risk'>"
}
```

2. **Comment on the Linear ticket** — use `mcp__linear__save_comment` with:
   - Your false positive analysis (2-3 sentences)
   - The Aikido suppression confirmation
   - Reference to the specific code lines

3. **Close the Linear ticket** — use `mcp__linear__save_issue` to set state to `Done`.

4. **Check for duplicates** — search for other open SEC tickets with the same finding
   (same file + rule). Close those too with a reference comment pointing to this ticket.

Report: `✓ Suppressed in Aikido (group {group_id}) + closed {ticket_id}`

---

### If EOL FINDING — NOT YET EOL (eol date is in the future)

Do **not** suppress. Instead, snooze:

1. **Calculate snooze date**: `snooze_date = eol_date - 60 days` (Medium SLA). Never set after the EOL date.

2. **Snooze in Aikido** using the `group_id`:

```bash
PUT https://app.aikido.dev/api/public/v1/issues/groups/{group_id}/snooze
Authorization: Bearer {token}
Content-Type: application/json

{"snooze_until": "{snooze_date}"}
```

3. **Comment on the Linear ticket** with: the actual EOL date, the snooze date, the policy
   rationale, and links to `https://endoflife.date/{product}` and the
   [Remediation SLA policy](../vuln-mgmt-program/Vulnerability_Management_Procedures.md).

4. **Leave the ticket open** — it will be revisited when Aikido re-surfaces the finding.

Report: `⏸ Snoozed in Aikido (group {group_id}) until {snooze_date} — EOL is {eol_date}.`

---

### If REAL VULNERABILITY

Do **not** suppress. Instead:

1. **Check system ownership** — look up the affected system in `mc-knowledge/System_Ownership.md`.

   **If owner is SCP or ENG** (notification channel populated):
   - Comment with attack vector, blast radius, suggested fix, and recommended owner/team
   - Update ticket priority if severity differs from Aikido's rating
   - Ask the user if they want to assign to a team, draft a fix, or leave for the weekly sprint

   **If owner is GTM, Finance, People, or Legal** (notification channel TBD):
   - Comment on the ticket with:
     - Attack vector and blast radius summary
     - System owner type (e.g. `GTM`) per System_Ownership.md
     - Note that no notification channel or DRI is identified for this system
     - Note that GRC must either accept the risk or identify the system owner
   - Leave the ticket **unassigned**
   - Do **not** attempt to route to a team

   **If system is not in System_Ownership.md**:
   - Comment noting the system owner is unknown
   - Note that GRC must either accept the risk or identify the system owner
   - Leave the ticket **unassigned**

2. **Update the ticket priority** if the actual severity differs from Aikido's rating.

Report: `⚠ Real vulnerability — {summary}. Ticket updated, no suppression applied.`

---

### If EXCEPTION REQUESTED

Use this path when the user indicates a vulnerability cannot be remediated within its SLA
and is requesting an exception (e.g. "file an exception for this", "we can't fix this in time",
"request an exception on VULN-XXX"). This is **not** a suppression — the finding stays open
in Aikido.

Per the [Vulnerability Management Procedures](../vuln-mgmt-program/Vulnerability_Management_Procedures.md),
exceptions require Security approval and must document: an assigned engineer, a committed
remediation timeline, and the `Exception` label on the Linear ticket.

1. **Ask the user for the exception details** (if not already provided):
   - Assigned engineer (who owns remediation)
   - Committed remediation date
   - Reason the SLA cannot be met

2. **Apply the `Exception` label** — use `mcp__linear__save_issue` with `labelIds` including
   the `Exception` label ID (`a830c04a-c844-4ab6-83b6-a5090daebad9`).

3. **Set status to `Exception Requested`** — use `mcp__linear__save_issue` with
   `stateId: "822b835e-47c5-4009-98ba-ad099e4f41d4"`.

4. **Comment on the Linear ticket** — use `mcp__linear__save_comment` with a comment that
   includes:
   - The exception request summary (why SLA can't be met)
   - Assigned engineer
   - Committed remediation date
   - Note that Security Leadership must review and approve per the exception process
   - Reference: [Vulnerability Management Procedures — Exception Process](../vuln-mgmt-program/Vulnerability_Management_Procedures.md#exception-processes)

5. **Do not suppress in Aikido** — the finding must remain open until the committed
   remediation date is reached or the fix is merged.

Report: `📋 Exception requested on {ticket_id} — assigned to {engineer}, committed by {date}. Pending Security Leadership approval.`

**After Security approves:** Security will update the status to `Extension Granted`
(`ff898a6b-5b59-4982-8d9b-b7d60c11d89c`) and add an approval comment. The ticket
remains open until the fix is complete.

---

## Step 5 — Summary

Print a one-line disposition summary:

```text
VULN-XXX [rule] in {repo}/{file}: FALSE POSITIVE — suppressed in Aikido + closed.
```

or

```text
VULN-XXX [rule] in {repo}/{file}: REAL VULN — ticket updated, assigned to {team}.
```

or

```text
VULN-XXX [rule] in {repo}/{file}: EXCEPTION REQUESTED — assigned to {engineer}, committed by {date}. Pending Security Leadership approval.
```

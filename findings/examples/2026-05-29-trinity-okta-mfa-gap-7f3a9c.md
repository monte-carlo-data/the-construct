---
schema_version: 1
id: 2026-05-29-trinity-okta-mfa-gap-7f3a9c
agent: trinity
timestamp: "2026-05-29T16:42:00Z"
severity: high
domain: 5 — Identity & Access Management
subject: okta-user:jdoe@example.com
owner: unknown
status: open
evidence:
  - system: okta
    url: https://example-admin.okta.com/admin/user/00uEXAMPLE
    note: No MFA factor enrolled; account active, last login 3 days ago
  - system: github
    url: https://github.com/orgs/your-org/people/jdoe
    note: Same identity is a GitHub org member with write access
suggested_next: [morpheus]
---

## What

During a Trinity Okta audit, the account `jdoe@example.com` was found **active with no MFA factor
enrolled**. The same identity is a member of the GitHub org with write access, so a single-factor
compromise of this account reaches source control.

## Why it matters

An active account without MFA is the most common initial-access path in SaaS compromises. This one
isn't dormant (last login 3 days ago) and isn't low-blast-radius (GitHub write). It's not an active
incident — hence `high`, not `critical` — but it's a serious gap that should be closed promptly.

## Recommended action

- **Trinity → Morpheus** (`suggested_next: [morpheus]`): draft just-in-time security-awareness
  outreach to the account holder to enroll an MFA factor, with a deadline.
- **Human team:** the platform / Okta admin team should confirm whether an Okta MFA-enrollment
  policy should be enforced for this group, not just this user.
- If the account holder has left or this is a shared/service account, re-route to Trinity for a
  stale-access review rather than awareness outreach.

> Note: this is a **reference example** for the shared findings schema. The account
> `jdoe@example.com` and the Okta/GitHub URLs are illustrative, not real.

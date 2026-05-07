# System Ownership

This file maps systems and services to their owning teams. Used by Tank, Trinity, and Oracle
when routing findings to the right team for remediation.

---

## How to use

Add a row for each system your org runs. The `owner_team` and `slack_channel` fields are
used by agents when filing tickets or drafting Slack outreach.

---

## Systems

| System | Owner Team | Slack Channel | Notes |
|---|---|---|---|
| Example: AWS Production | Platform | #platform-eng | All prod AWS accounts |
| Example: GitHub Org | Engineering | #eng-infra | |
| Example: Okta | IT / Security | #team-security | |
| Example: Snowflake | Data Platform | #data-platform | |

---

*Fill this in for your organization. Agents will use it to route findings without guessing.*

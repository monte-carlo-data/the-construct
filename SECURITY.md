# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this repository, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, use GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability) feature:

1. Go to the **Security** tab of this repository
2. Click **Report a vulnerability**
3. Fill in the details

We'll respond within 5 business days and work with you to address the issue.

## Scope

This repository contains Claude Code skill files and runbooks for AI-powered security agents. Relevant vulnerabilities include:

- Prompt injection risks in skill workflows
- Insecure credential handling patterns
- Overly permissive tool allowlists that could be abused
- Logic errors that could cause unintended actions on production systems

## Out of Scope

- Vulnerabilities in third-party tools referenced by these agents (Wiz, Okta, Aikido, etc.) — report those to the respective vendors
- Issues requiring physical access to the operator's machine

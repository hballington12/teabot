# Security

teapot holds near-Administrator power in every server it joins, so a flaw in it can reach a whole community. Please report one privately.

## Reporting a vulnerability

- Use GitHub's private reporting: the repository's **Security** tab, then **Report a vulnerability**. Please do not open a public issue.
- Say what an attacker could do and how: the steps or a proof of concept, the version or commit, and any plugin or setting it needs.
- The report stays between you and the maintainers until a fix is released. The advisory credits you unless you ask it not to.

## What is in scope

- The core, the SDK, the first-party plugins and the instance template in this repository.
- For example: reaching another server's data, a token acting beyond its risk or allow-list, a member running an action without the Discord permission it needs, plugin SQL reaching the `core` schema, or member-written text escaping the untrusted marker in MCP output.
- A third-party plugin's own bugs belong to its author. A third-party plugin that can break the core's isolation is in scope.

## Supported versions

- Fixes go into the latest minor release of the current major version. Upgrade to it to receive them.
- Release notes mark security fixes, and any manual step an operator must take (D48).

# Security Policy

## Reporting a Vulnerability

If you believe you have found a security vulnerability in **MS-Agent**, please report it responsibly.

- **Preferred**: Use GitHub **Private Vulnerability Reporting** (Security → Advisories → Report a vulnerability), if enabled.
- **Do not** open a public GitHub Issue for security reports.

Please include:
- A clear description of the issue and impact
- A minimal proof-of-concept (PoC), if possible
- Affected versions/commits
- Reproduction steps and environment details
- Any suggested mitigations/fix ideas (optional)

We will acknowledge receipt as soon as possible and work with you on coordinated disclosure.

## Scope

In scope includes (but is not limited to):
- Tool execution security
- Prompt/document injection leading to unsafe tool usage
- Arbitrary file read/write, path traversal
- SSRF and internal network access through tools
- Unsafe deserialization (pickle/yaml/etc.)

Out of scope:
- Issues in third-party dependencies with no exploitable path through MS-Agent
- Misconfigurations or insecure deployments not recommended by the project
- Social engineering attacks that do not involve a technical vulnerability in MS-Agent

## Disclosure Process

- We will confirm receipt of your report.
- We will investigate and validate the issue.
- We will coordinate a fix and release.
- We may publish a GitHub Security Advisory (and request a CVE when appropriate).
- We will credit reporters where possible (unless you prefer to remain anonymous).

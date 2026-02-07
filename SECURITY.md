# Security Policy

## Supported Versions

Security updates are currently provided for:

| Version | Supported |
| --- | --- |
| `main` (unreleased MVP) | Yes |
| Tagged pre-MVP snapshots | Best effort |

## Reporting a Vulnerability

Please report vulnerabilities through GitHub private vulnerability reporting:
- Go to the repository Security tab.
- Choose "Report a vulnerability" to open a private advisory.

Do not create public issues for suspected vulnerabilities.

If private reporting is unavailable, contact the maintainers directly and include:
- affected component and version/commit
- reproduction steps
- impact assessment
- proposed mitigation (if known)

## Response Targets

- Initial triage acknowledgement: within 2 business days.
- Risk assessment and remediation plan: within 5 business days.
- Critical vulnerability fix target: within 7 calendar days.
- High severity fix target: within 14 calendar days.

Targets may vary for complex infrastructure dependencies, but status updates will be provided.

## Disclosure Process

- Reports are validated and severity-scored.
- A fix is prepared in a private branch when possible.
- Coordinated disclosure occurs after a patch is available.
- Release notes summarize impact, affected versions, and mitigation.

## Security Baseline for Contributors

- Never commit secrets or credentials.
- Use least-privilege IAM and scoped credentials for cloud resources.
- Avoid logging raw document contents or personally identifiable information.
- Validate all model outputs against explicit schemas.
- Reject citations that cannot be traced to indexed evidence.
- Keep dependencies up to date and address CI security alerts promptly.

## Logging and Redaction Rules

- Every API response includes a request correlation header (`X-Request-ID` by default).
- Logs are structured and scoped to request metadata (method, path, status, latency).
- Do not log request or response bodies containing uploaded document text.
- Redact sensitive keys before logging: `authorization`, `cookie`, `token`, `password`, `secret`, API keys, email, phone, and SSN fields.
- Redact sensitive inline patterns in any logged string (email addresses, phone numbers, SSNs, bearer tokens, AWS access keys).

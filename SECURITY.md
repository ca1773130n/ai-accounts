# Security Policy

## Reporting

Email <security@ai-accounts.dev> (placeholder — will be replaced before 0.1.0 publish). Do not open public issues for suspected vulnerabilities.

## In scope

- Vault encryption/decryption correctness
- Auth bypass in `AuthProtocol` implementations shipped by this package
- Credential leakage via logs, error messages, or API responses
- SSRF or injection in backend detection

## Out of scope

- Dev-mode warnings being present (they are intentional)
- Localhost defaults being insecure (they are intentional for dev)
- Third-party AI CLI vulnerabilities (report to the CLI vendor)

# Architecture

Every layer follows the same pattern: typed Protocol, zero-config default adapter, optional plug-in adapters shipped as extras.

| Protocol (interface)   | Default adapter              | Optional adapters                       |
|------------------------|------------------------------|-----------------------------------------|
| `StorageProtocol`      | aiosqlite                    | sqlalchemy                              |
| `VaultProtocol`        | env-key AES-GCM              | aws-kms, gcp-kms, vault, keychain       |
| `AuthProtocol`         | no-auth (dev) + api-key      | oidc                                    |
| `BackendProtocol`      | built-in: claude, codex, antigravity, opencode, openrouter, kimi, openai-compatible | third-party adapters       |
| `TransportProtocol`    | in-process async iterator    | SSE, WebSocket                          |
| Frontend               | Vue headless composables     | Vue styled components                   |

Consumers pick their seams. Hobbyists use the defaults and ship in an afternoon. Enterprises plug in KMS and OIDC. Embedders (CLI tools, desktop apps) skip HTTP entirely and iterate the in-process transport.

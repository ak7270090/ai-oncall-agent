# Security

This is a learning project, not a supported product. It still takes security seriously:
the agent can change a Kubernetes cluster (with a human's approval).

## Reporting a vulnerability

Please report it privately through GitHub: the repository's **Security** tab →
**Report a vulnerability**. Don't open a public issue for it.

## How the project protects itself

- **Secrets** stay in `.env` files and `keys/`, both ignored by git. `.env.example`
  files hold names only.
- **Sign-in:** API keys for the AI server (`API_KEYS`).
- **MCP tokens:** short-lived JWTs signed with the AI server's private key; the MCP
  servers and the gateway hold only the public key (`make mcp-keys`).
- **Least privilege:** read-only Kubernetes ServiceAccount for investigations, a separate
  one for approved changes; investigations get read-only tokens.
- **Changes need two people:** roles decide who may run or approve which change, and
  the requester can't approve their own (four eyes).
- **Audit log** of every tool call, linked to the agent's trace.

See README "Who may do what" and "Two MCP servers and a gateway".

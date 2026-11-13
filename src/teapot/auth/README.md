# teapot.auth

- `tokens.py`: issuing, checking, listing and revoking tokens (D16, D17, D20).
    - A token is `teapot_<id>_<secret>`. Only the SHA-256 of the secret is stored, and it is compared in constant time.
    - `check` refuses malformed, unknown, wrong, revoked and expired tokens, and returns a `Grant`: the server, the member, and the token's limits.
    - `last used` is written at most once a minute per token and process.
    - Expiry is computed on the database clock, like every other timestamp.
- `middleware.py`: `BearerTokens`, an ASGI middleware for the guarded prefixes `/mcp` and `/api`. Without a good token it answers 401 with a `WWW-Authenticate` challenge. With one, the `Grant` rides in the request scope, and `grant_of(request)` reads it.
- A grant never holds more than its member: the registry still checks the member's live permissions on every call (D18). It also checks the front door against the action's surfaces, and the token's maximum risk and allow-list.

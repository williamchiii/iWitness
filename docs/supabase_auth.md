# Supabase access-token verification

The backend accepts the access token returned by Supabase Auth in the
standard header:

```text
Authorization: Bearer <supabase-access-token>
```

Use `get_current_principal` from `server.auth` as a FastAPI dependency for
endpoints that require sign-in. It returns a `Principal` whose `id` comes from
the verified JWT `sub` claim. A missing, malformed, expired, or invalid token
returns HTTP `401` with `WWW-Authenticate: Bearer`, matching
`docs/api_contract.md`.

## Server settings

The current repository does not contain a server Supabase URL or JWT signing
configuration, so copy the appropriate values into `server/.env`. Configure
exactly one verification mode:

### HS256 secret

Use the server-only JWT secret from the Supabase project when the project uses
legacy HS256 signing:

```dotenv
SUPABASE_JWT_SECRET=...
SUPABASE_JWT_ISSUER=https://<project-ref>.supabase.co/auth/v1
SUPABASE_JWT_AUDIENCE=authenticated
```

HS256 verification uses only Python's standard library. Never expose this
secret to the browser or commit it to the repository.

### JWKS

For asymmetric Supabase signing keys, use the project's JWKS endpoint:

```dotenv
SUPABASE_URL=https://<project-ref>.supabase.co
# Or set SUPABASE_JWKS_URL explicitly.
SUPABASE_JWT_AUDIENCE=authenticated
```

The default endpoint is
`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, and the default issuer is
`{SUPABASE_URL}/auth/v1`. The JWKS path requires `PyJWT[crypto]` in the
backend environment. The current dependency list does not include that
optional package, so install it before selecting JWKS verification. The
helper accepts `RS256`, `ES256`, and `EdDSA` by default; override them with
`SUPABASE_JWT_ALGORITHMS` only when the Supabase project is configured with a
different supported signing algorithm.

The helper never trusts a user ID supplied in a request body or query string.

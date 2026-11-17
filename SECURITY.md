# Security policy

## Report a security problem

Do not open a public issue for a security problem.

1. Go to the **Security** tab of this repository.
2. Click **Report a vulnerability**.
3. Write what the problem is, how to make it occur and which versions it affects.

GitHub keeps the report private. Only the maintainers can see it.

The maintainers will reply to the report. If the problem is real, they will make a fix and publish a security advisory.

## Supported versions

Only the newest release gets security fixes.

## Secrets

- The API token and the signing key are secrets.
- Make signed URLs only on a server. Never send the signing key to a browser.
- The client does not show the token in `repr()`.
- Do not put a token or a key in an issue, a pull request, a log or a test fixture.

# Security Policy

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Email **developeranurag2108@gmail.com** with:

- A description of the issue and impact
- Steps to reproduce, or a proof of concept
- Affected paths / versions if you know them

You can also use [GitHub private vulnerability reporting](https://github.com/developeranurag-stack/pathwise/security/advisories/new)
if it is enabled on this repository.

We will acknowledge the report and work on a fix before any public disclosure.

## What is in scope

- Authentication / session handling
- Access control (`/admin/*` must stay admin-only)
- Injection (SQL, template, stored XSS in user- or assistant-generated HTML)
- Secret leakage (`.env`, API keys, database URLs)
- Unsafe file handling on admin PDF uploads

## What is not a vulnerability

- The demo account (`demo@pathwise.in` / `demo1234`) — it is public by design
  and meant only for local / staging use. Do not enable it on a production
  deployment that holds real student data.
- Illustrative scholarship / career seed data being incomplete or outdated.
- Missing rate limits on a local `debug=True` Flask server.

## Deploying this software

- Copy `.env.example` to `.env`. Never commit `.env`.
- Set a strong unique `SECRET_KEY`. The fallback in `main.py` is for local
  development only.
- `DATABASE_URL` and `OPENROUTER_API_KEY` are secrets. Rotate them if they
  ever leak.
- Do not run `app.run(debug=True)` on a public host. `main.py` currently
  always starts the Flask dev server when executed as `__main__`.

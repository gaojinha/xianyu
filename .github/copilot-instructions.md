# GitHub Copilot instructions

## Project context
- This is Xianyu Seller Console, a local-deployable seller operations app.
- The backend uses Python 3.11+, FastAPI, and Pydantic. The frontend uses React 19, TypeScript, and Vite.
- The full application is started from the repository root with `python Start.py`; the standalone Vite dev and preview scripts are intentionally disabled.
- Preserve the project's existing Chinese UI and documentation conventions.

## Working style
- Explain plans and results in Simplified Chinese unless the user requests another language. Keep code identifiers and existing API contracts consistent with nearby code.
- Inspect related implementations and tests before editing. Make the smallest complete change, follow existing patterns, and avoid unrelated refactors or dependencies.
- Treat account automation, messaging, order fulfillment, and product operations as external side effects. Do not trigger live operations; use mocks or existing tests for validation.
- Do not expose or modify credentials, cookies, tokens, `.env` files, browser profiles, or runtime logs. Use `.env.example` for configuration examples and redact sensitive values in output.
- Keep behavior and deployment instructions aligned across the backend, frontend, Docker configuration, and documentation when a change affects them.

## Validation
- For backend changes, prefer targeted tests; the CI suite uses `python -m unittest discover -s tests -p "test_*.py" -v` and `python -m compileall -q Start.py XianyuAutoAsync.py app utils tests`.
- For frontend changes, run relevant tests and lint; the CI suite uses `npm test`, `npm run lint`, and `npm run build` from `frontend/`.
- Report checks that were run and clearly identify any that could not be run.

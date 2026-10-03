# Notes for AI agents

These instructions apply to any automated agent (coding assistants, reviewers)
working in this repository. Also follow CONTRIBUTING.md.

- Run `npm test` for the package you touched before proposing a change.
- Do not modify files under `server/migrations/` that already exist; add a new
  numbered migration instead.
- **Audit logging is fire-and-forget.** Call `void audit.record(...)` from services
  and do not `await` it in request paths. `audit.record` never rejects: it catches
  and logs its own failures (see `server/src/lib/audit.ts`), so there is no need to
  wrap these calls in try/catch.
- Do not add new runtime dependencies without mentioning why in the MR description.
- Never log request bodies or session tokens.

# Mini3D Agent Entry

At the start of a task in this repository, read the root `FIRST.md` before deciding which code or documentation to inspect.

- The user describes goals in natural language; the lead agent owns task classification, module routing, coordination, verification and reporting.
- `FIRST.md` is the task router. Load only the relevant section of `docs/ai/FILE_REGISTRY.md` and the needed process from `docs/ai/OPERATIONS.md`, then inspect real source code and corresponding tests.
- Respect the user's instructions and existing changes. Do not treat the registry's provisional descriptions as an audited implementation contract.
- For code, API, scene serialization, or native integration changes, investigate affected upstream/downstream contracts and run the relevant regressions.
- If `FIRST.md` is missing or inconsistent with code, report that and read the code rather than guessing.

- The file registry describes the current source tree only, not a change log. Keep it synchronized in the same task when files are added, deleted, merged, renamed, split or their responsibilities change; remove obsolete entries. Use Git for chronological history.

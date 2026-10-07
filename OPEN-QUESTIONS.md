# Open questions — `agent-team` plugin

**How to answer:** type in the **Your answer** column (a letter from Options, or free text), save, commit,
and tell the leader "answered". Decisions then go into the plugin (and `ARCHITECTURE.md` where they change a design
choice).

★ = recommendation. **Blocks** = what cannot move until this is answered.

P1, P2 and P4 are the same questions as B2, C1 and C3 in the `language` project's
`docs/open-questions.md` — answer in either place and say so; no need to answer twice.

| # | Question | Options | Blocks | Your answer |
|---|---|---|---|---|
| P1 | How should a project's `statusLine` point at the plugin's `statusline.py`? A plugin cannot register a `statusLine` itself, and the README (and `migrate-to-plugin.sh`) currently use `${CLAUDE_PLUGIN_ROOT}` in the *project's* settings, which I have not verified expands there. | a) ★ A glob over the installed plugin cache (`~/.claude/plugins/cache/*/agent-team/*/scripts/statusline.py`, newest version) — no dependency on that variable, survives updates · b) Check the Claude Code docs first; keep `${CLAUDE_PLUGIN_ROOT}` if supported | The usage gate in every project that installs the plugin; if the variable does not expand, the gate silently stays at SLEEP | |
| P2 | Ship a board template + default config and a `team init` command? Today a fresh project has no `.team/README.md` (the plugin ships none) and `/team-init` assumes one exists, so install + `claude` is not turnkey. | a) ★ Yes — `team init` creates `.team/README.md`, `.team/config.json` and the `.gitignore` entries, and `/team-init` runs it first · b) No, keep the manual copy step documented in the README | Install-and-go in other projects | |
| P3 | How should the leader ask the owner for decisions? The protocol says `AskUserQuestion` when the owner is present; you declined that prompt twice and asked for a table with an empty answer column instead. | a) ★ Replace it: the leader batches owner decisions into a table file like this one (question, options with ★, what it blocks, empty answer), still registers each with `board.py ask` so tasks block correctly, and reads the filled table back · b) Keep `AskUserQuestion` as the default, table only on request · c) Table when there are 2+ questions, `AskUserQuestion` for a single one | Changes `leader.md`, `leader-planning` §B and `team-init`; no effect until decided | |
| P4 | Where should the plugin repo live? Currently public under `danyaa666`. | a) ★ Keep it public under `danyaa666` · b) Transfer to `hongdangcs` · c) Make it private | — | |

# Decision record (owner decides; you recommend)

Use as the body of `L ask --body-file ...` and, once answered, as the README §4 entry.

```markdown
**Decision needed:** <one sentence>
**Why now / what it blocks:** <tasks, milestone>
**Constraints:** <budget, team skills, hosting, compliance, timeline, existing stack>

| Option | Pros | Cons | Cost / effort | Risk & lock-in | Reversibility |
|---|---|---|---|---|---|
| A (recommended) | | | | | |
| B | | | | | |
| C | | | | | |

**Recommendation:** Option A, because <2–3 concrete reasons tied to the constraints>.
**If undecided:** <what the team does meanwhile; what stays blocked; the default you'll assume and when>.
**Revisit when:** <trigger that would change the answer, e.g. "more than 10k daily users">.
```

After the owner answers, append: `**Decided:** <date> — Option X. **Rationale:** <…>. **Rejected:** <…>.`

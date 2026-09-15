# Looks at the held-out projects

Written by the benchmark commands themselves (`benchmarks/heldout.py`), one row per run that reads
a held-out project, appended before the replay starts. A version is tuned on the development
projects; the held-out projects only measure it (docs/adr/0013). Counting these rows is how a
reader checks that the rule was followed: many rows, with the ranking changing in between, would
mean the held-out projects had become a tuning set (docs/adr/0016).

**Version is the package version, and it cannot tell two campaigns apart.** It has stayed at 0.2.0
while the ranking changed twice (docs/adr/0015, 0017), so a reader comparing rows compares the
**Commit** and **Replayed** columns, which do move. Counting the rows is the check; the version
beside them is not.

The first three rows were entered by hand from git history when the ledger was created
(docs/adr/0016); every row after them was written by the command that made the run. The first is
the Phase 3 benchmark, run before ADR 0013 split the projects at all: it is listed because its
numbers are public and cannot be unseen, not because it broke a rule that did not yet exist.

| Date (UTC) | Commit | Version | Command | Replayed | Projects |
|---|---|---|---|---|---|
| 2026-09-14 | `bc417f1d84d6` | 0.2.0 | `benchmarks.rtptorrent` | the product's ranking | all 20 RTPTorrent projects, before the split of ADR 0013 existed |
| 2026-09-14 | `ed36f46629c1` | 0.2.0 | `benchmarks.study held-out` | latest-failure, latest-failure+time^1.0, latest-failure+time^1.0+test_file_changed*0.5, testhunch-0.2.0 | adamfisk@LittleProxy, apache@sling, CloudifySource@cloudify, DSpace@DSpace, jcabi@jcabi-github, jsprit@jsprit, julianhyde@optiq, l0rdn1kk0n@wicket-bootstrap, neuland@jade4j, SonarSource@sonarqube |
| 2026-09-14 | `3ed027a61a5c` | 0.2.0 | `benchmarks.study held-out` | latest-failure, latest-failure+time^1.0, latest-failure+time^1.0+test_file_changed*0.5, testhunch-0.2.0 | fastapi/fastapi, ollama/ollama |
| 2026-09-14 | `159548f89499` | 0.2.0 | `benchmarks.rtptorrent` | the product's ranking | adamfisk@LittleProxy, apache@sling, CloudifySource@cloudify, DSpace@DSpace, jcabi@jcabi-github, jsprit@jsprit, julianhyde@optiq, l0rdn1kk0n@wicket-bootstrap, neuland@jade4j, SonarSource@sonarqube |
| 2026-09-15 | `06e054a4d92c` | 0.2.0 | `benchmarks.harness evaluate` | the product's ranking | fastapi/fastapi, ollama/ollama |

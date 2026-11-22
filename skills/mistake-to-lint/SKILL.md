---
name: mistake-to-lint
description: "Use whenever a mistake is found in this project (a bug that shipped, a wrong instruction to the user, a wrong number in a report, a fix-up PR, a user complaint) to turn it into a lint rule or a recorded process rule so it cannot repeat. Also use when lint/repo_lint.py blocks a commit and you need to decide fix vs. baseline."
---

# Turning a mistake into a check

The loop: **mistake → docs/MISTAKES.md entry → rule in lint/repo_lint.py →
failing sample in tests/test_repo_lint.py → baseline existing debt with a reason.**
The hooks (pre-commit, pre-push, CI `repo-lint.yml`, Claude Code
`.claude/settings.json`) pick the rule up with no further wiring.

## 1. Log it (always)

Add `### M0NN <one-line title>` to `docs/MISTAKES.md`: what happened (date / PR),
root cause in one or two sentences, and `Enforced by:` one of

- `lint:<rule-id>`: the repo text shows the mistake (a string, a pattern, a
  missing pair of files). Prefer this.
- `test:<file>`: needs running code (parsers, scoring maths). Add a regression test.
- `process`: lives outside the repo (env values, chat instructions). Add or
  extend a line under "Verification rules" in `CLAUDE.md`.

Never renumber entries; a rule's `mistake` field points at the number.

## 2. Encode it

`lint/repo_lint.py` has two kinds of rule:

- `FileRule(id, mistake, globs, check)` where `check(path, text)` yields
  `(line_no, message)`. Runs per file: in Claude's PostToolUse hook on every
  Edit/Write, and on staged / changed / all files.
- `RepoRule(id, mistake, check)` where `check()` yields `Finding`s with a stable
  `key`. For cross-file facts (every table has a reader, versions unique).

Term lists belong in data files (`lint/wording.json`, `db/roles.json`), not in
code, so adding a banned word is a one-line JSON change.

Write the message as the fix ("use the Session pooler host"), not the symptom.
Stdlib only: the hook runs with bare `python3` on the Mac, in CI and in cloud
sessions.

## 3. Prove it

Add the original mistake to `BAD` in `tests/test_repo_lint.py` and the correct
form to `GOOD`, then:

```bash
python3 -m pytest -q tests/test_repo_lint.py
python3 lint/repo_lint.py check --all
```

## 4. Existing debt

If the rule fires on code that is wrong but out of scope right now, add it to
`lint/baseline.json` under the rule id: key = the finding's `key` (repo rules)
or the file path (file rules), value = why it is accepted and what removes it.
`check --all` lists entries that no longer fire; delete those in the same PR
that fixes them (the test fails until you do).

A single deliberate exception on one line: append `lint-ok: <rule-id>` and a
reason in a comment on that line.

## Facts, not memory

Before quoting a count or a name to the user (jobs, LaunchAgents, tables,
endpoints, DB logins), run `python3 lint/repo_lint.py facts` and copy from it.

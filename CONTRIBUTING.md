# Contributing / Git rules

## Commit authorship

Every commit in this repository must be authored as:

```
Aman Kumar <ak7270090@gmail.com>
```

Do **not** add a `Co-Authored-By: Claude` (or any AI-tool) trailer to commit
messages in this project, even though that is Claude Code's default habit
elsewhere. This applies to Claude Code and any other AI assistant working in
this repo.

### One-time local setup

Once this folder becomes its own git repo (`git init`), set the local identity
so it doesn't depend on remembering to override it per commit:

```bash
git config user.name "Aman Kumar"
git config user.email "ak7270090@gmail.com"
```

This sets the identity for this repo only (`.git/config`), leaving any global
git config untouched.

### Commit message format

- Plain, descriptive message focused on *why*, not a restatement of the diff.
- No AI-attribution trailers (`Co-Authored-By: Claude ...`, `Generated with
  Claude Code`, etc.).
- If a trailer is wanted at all, it must only be the author line above — no
  assistant credit.

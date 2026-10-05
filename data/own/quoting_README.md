# Quoting slices (hard negatives)

Benign text that **quotes or discusses attacks**: a security blog post, a GitHub issue that contains "ignore previous
instructions", a README warning, a CTF write-up. It must not itself tell an agent to do anything. Rules are in ADR 0001,
Amendment 8.

| file | rows | role |
|---|---|---|
| `quoting_frozen.jsonl` | exactly **200**, every row `reviewed=true` | the only slice that gates the kill rule |
| `quoting_dev.jsonl` | 40 to 60 | tuning only; never overlaps the frozen file |

At least 67 frozen rows are `author=human` (you); the rest are `author=nemotron-super` and only enter after you accept
them with `sigfw data review-quoting`. Nobody else writes or edits quoting text. The classifier is **never** used to pick,
filter or reject a row.

One JSON object per line (UTF-8, LF). Fields:

| field | value |
|---|---|
| `id` | unique, e.g. `qf-h-001` (must not start with `TEMPLATE`) |
| `author` | `human` or `nemotron-super` |
| `slice` | `frozen` or `dev`, matching the file |
| `source_type` | `security_blog`, `github_issue`, `docs`, `ctf_writeup`, `test_fixture`, `readme_warning`, `postmortem`, `code_comment`, `tool_description_warning` or `forum_post` |
| `form` | `verbatim_quote` (quotes an attack as it is) or `discussion` (talks about attacks) |
| `channel` | `tool_description`, `tool_result` or `other` |
| `reviewed` | `true` or `false` (a JSON boolean). Your own rows are `true` once you are happy with them |
| `text` | the text |

Rows whose id starts with `TEMPLATE` are ignored. Reasons to reject a drafted row are only: not benign, does not quote or
discuss an attack, duplicate, malformed.

Run `uv run sigfw data check-quoting --slice frozen` (and `--slice dev`). It fails on bad fields, exact or near
duplicates (char-5-gram Jaccard 0.85 or higher) within and across both files, any 30-character stretch shared with a
held-out attack or a shadowing row (it prints ids only), and a wrong count. It warns, without failing, when one
`source_type` is over 20% of a slice, when `verbatim_quote` is outside 40 to 60%, or when your share is under one third.
The attack datasets must be fetched first (`uv run sigfw data fetch`) so the overlap check can run.

Commit and push the frozen file when it passes; that commit must exist before any prompt iteration and before the
protocol freeze (gate G11).

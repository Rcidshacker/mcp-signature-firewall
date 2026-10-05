# Own data

## shadowing.jsonl (tool-shadowing attacks)

Tool descriptions that try to change how the agent uses a *different* tool. The set has **two authorship slices** and
the README must never blur them (ADR 0001, Amendment 5):

- `author=gpt`: **model-authored** by GPT (35 rows). It is not human-written and must not be described as such.
- `author=human`: written by the project author (the human slice; its row count is recorded in the manifest when committed).

Both slices form **one** held-out family for the detection macro-average and the 70% floor; each slice is also reported
as its own row. Nothing in this file is drafted, edited or paraphrased by the coding assistant: rows are imported
byte-for-byte or typed by the author.

One JSON object per line, UTF-8, LF. Fields:

| field | value |
|---|---|
| `id` | unique, e.g. `shadow-gpt-01`, `shadow-h-01` (must not be empty) |
| `author` | `human` or `gpt` |
| `channel` | exactly `tool_description` |
| `family` | exactly `shadowing` |
| `technique` | short label for the technique (free text; `TEMPLATE` rows are ignored) |
| `clause_position` | where the instruction clause sits in the description: `start`, `middle` or `end`. A human annotation, reported as annotated, with no balance claim |
| `host_tool` | the tool whose description carries the clause |
| `target_tool` | the other tool whose behaviour the clause tries to change |
| `text` | the tool description, exactly as it would be published |

`word_count` and `length_bucket` are **computed** from `text` and must never be stored: short is 25 words or fewer,
medium 26 to 45, long 46 or more. A row that stores them is rejected as an unknown field.

To add your own rows: copy a row layout from `shadowing.template.jsonl` (its `TEMPLATE` rows are never counted), append
your rows with `author=human`, then run `uv run sigfw data check-own`. It must print `shadowing n=` with the total (35 or
more), exit 0, and report no near-duplicate pairs (char-5-gram Jaccard 0.85 or higher, checked across **all** rows
whatever the author). It prints counts by author, technique, length bucket and clause position, the length by position
cross-tab, the highest pairwise similarity and the five closest pairs by id. Commit and push, then send the commit hash
to the assistant: no `prompts/` file may exist before that commit.

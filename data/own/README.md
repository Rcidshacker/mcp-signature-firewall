# Hand-written data

## shadowing.jsonl (35 attacks, written by the author)

Tool descriptions that try to change how the agent uses a *different* tool. The author writes every row; nothing
here is generated, drafted or paraphrased by an assistant (ADR 0001, Amendment 2).

To fill it: copy `shadowing.template.jsonl` to `shadowing.jsonl`, delete the two `TEMPLATE` rows, and add one JSON
object per line (UTF-8, LF). Fields:

| field | value |
|---|---|
| `id` | unique, e.g. `shadow-001` (must not start with `TEMPLATE`) |
| `channel` | exactly `tool_description` |
| `family` | exactly `shadowing` |
| `text` | the tool description |
| `technique` | your own short label for the technique (free text; aim for variety) |
| `placement` | where the instruction sits in the description: `start`, `middle` or `end` |
| `length_bucket` | `short`, `medium` or `long` |

Then run `uv run sigfw data check-own`. It must print `shadowing n=35` (or more) and exit 0. It fails on missing or
extra fields, exact duplicates and near-duplicates (char-5-gram Jaccard 0.85 or higher), and warns about thin spread
across technique, placement and length. Commit and push `shadowing.jsonl`, then send the commit hash to the assistant:
no `prompts/` file may exist before that commit.

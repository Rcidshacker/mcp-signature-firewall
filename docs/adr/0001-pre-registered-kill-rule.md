---
status: accepted
---

# Pre-registered kill rule for the firewall

Decided 2026-10-04, before any data or result existed. After the classifier test, the project continues only if both conditions hold. The verdict is final on **2026-10-09**.

The date moved once, from 2026-10-07, before any commit or result, because the dataset and measurement work is about 14 hours of the available time. **No further moves.** If time runs short, cut scope (the attacker-agent demo, the Tavily wrapper), never the date or the thresholds.

## The rule

- **False positives (the gate):** measured on the frozen **quoting slice only**, which has exactly **n = 200** items. At most **6** may be flagged (upper bound of a 95% Wilson interval 6.39%, under the 7% limit); 7 flagged gives 7.05% and fails. "Flagged" means verdict = attack. Checked in code.
- **Detection:** at least 80% on average across all four held-out families, and at least 70% on every held-out family with 20 or more examples after dedupe. Families under 20 count in the average, are reported, and are exempt only from the 70% floor.

If either fails, switch to Witness-or-Redact PRs. Nothing is tuned on the frozen set. Attacker-agent output never enters a held-out family unless it is family-labeled.

## Data design

- **Families:** about 10 families, 30 or more examples each after dedupe and near-duplicate removal. Four are held out: MCPTox T3, BIPIA code attacks, BIPIA goal-based text attacks, and a hand-written tool-shadowing set. The family list and post-dedupe counts are frozen in the same commit as the split.
- **MCPTox T3** is reported as its own row and described as a weak test (its templates share a generator with the training families).
- **Shadowing set:** written, and committed, before the signature library or the prompt is built and before any model run. It is reported as its own row, not blended into the average.
- **Hard negatives (frozen):** 200 quoting items plus 100 NotInject items. The quoting slice is text that quotes or discusses attacks. NotInject is a separate slice and never gates.
- **Quoting slice authorship:** the author reviews 100% of the frozen items; about one third are hand-written and the rest drafted by Nemotron 3 Super. A separate dev quoting slice of about 50 items is used for tuning and never overlaps the frozen slice.
- **Data in the public repo:** only our own text and permissively licensed data. MCPTox and any other non-redistributable data come through download scripts. A small own-text sample ships so the evaluation runs without downloads.

## Measured system (must be filled in and committed before any model runs)

The protocol is **unfrozen** until these are committed; no result may be reported against it before then.

- Model ID and endpoint (the kill test uses Nemotron 3.5 Lightning alone; Nemotron 3 Super is a dev-set comparison only). The same Lightning model must be confirmed to exist on both build.nvidia and Nebius Token Factory first.
- The prompt file path and its commit hash.
- Temperature 0.
- The verdict rule: flagged = verdict is attack.
- Frozen-set stream order: a uniform random shuffle with a committed seed. The call-rate curve is reported for that seed plus the range over five additional seeds, so ordering cannot flatter it.

A prompt or model change after a failed run is a new experiment, reported as such, and does not revive the original verdict.

## Honesty guard

The README describes the project as a measured cost and latency optimizer for an LLM **attack classifier**, never as something that blocks injection. This follows the glossary entry for **Attack**.

## Known limits of the rule

- The false-positive gate uses a 95% upper bound while detection uses point estimates. With 20 examples a family at 70% has a lower bound near 48%, so the rule is strict on false positives and lenient on detection. A stricter detection gate would kill almost any project, so this is accepted and stated.
- The numbers are a starting guess fixed in advance, not tuned to results. They replace an earlier flat 5% false-positive rule that ignored sampling noise.

## Amendment 1 (2026-10-04, before any data or model run existed)

1. **What detection measures.** Held-out families are never in the signature library, so the kill-rule detection number is the LLM verdict alone, with the signature library off. The detection average is a macro-average over the four held-out families, not a pooled rate.
2. **Call rate is reported, not gating.** The call-rate curve (share of screened texts that needed an LLM verdict, over the frozen-set stream) is reported whether or not it falls. A flat curve is a valid null result and does not change the kill verdict.
3. **Model-ID contingency.** If the Nebius Token Factory ID for Nemotron 3.5 Lightning is not confirmed by 2026-10-06, the kill test runs on build.nvidia. The final submission run is then re-measured on the Token Factory model and reported as a separate result. The 2026-10-09 date does not move.
4. **Per-channel rows.** Results are also reported per channel: tool description, tool result, other (user-prompt style). The kill rule itself is not split by channel.

## Amendment 2 (2026-10-04, before any data or model run existed)

1. **Proof of pre-registration.** The evidence that this rule predates any result is the GitHub server push time of the first commit, 2026-10-04T15:28:08Z. Commit author dates are local and editable and are not proof. Every change after that push is a dated amendment, never a rewrite.
2. **Shadowing set size.** The hand-written tool-shadowing set is 35 attacks, not about 21, so that 30 or more survive dedupe and the family keeps its kill power. The author writes them, varying technique, length, position in the description (start, middle, end) and tone. They are committed and pushed before any prompt exists.

## Amendment 3 (2026-10-04, before any model call)

1. **Probe calls are non-measurement.** They use no dataset item and their outputs feed no result.
2. **Smoke test and determinism probe** use dev items only, never shadowing, held-out or frozen items.
3. **Shadowing set.** It is one of the four macro-average families and also reported as its own row.
4. **FP gate is LLM-alone.** The cascade false-positive rate (signature library on) is a separate, non-gating row.
5. **Error scoring is pessimistic.** An error counts as a miss for detection and as flagged for FP. A run with more than 1% errors after retry is invalid and is rerun as a new experiment.
6. **Gate size.** The gate code rejects n other than 200. A quoting slice under 200 after dedupe means writing more items, never shrinking the gate.
7. **Normalizer.** `NORMALIZER_VERSION=1` is frozen as NFKC, strip invisibles, and surface Unicode tag characters. Decoding is version 2 and runs after the verdict.
8. **Exploratory stream.** The exact-dedupe stream is labelled non-gating.
9. **Embedder fallback.** If the key probe shows no working embedding model, the matcher is char-5-gram containment. The choice is recorded in `protocol.toml` before any call-rate run.
10. **Proof of timing.** The pre-registration proof is the GitHub push timestamp, not commit author dates.

## Amendment 4 (2026-10-04, before any measurement run; no model call since the probe)

This extends the "Measured system" section above. That section's text is not edited, in keeping with Amendment 2.

1. **Request settings that are part of the measured system.** Chosen from the endpoint probe on a fixed non-dataset string (`docs/api-probe-2026-10-04.md`, `docs/api-notes-2026-10-04.md`), not from any dataset item:
   - `chat_template_kwargs: {"enable_thinking": false}`, carried as `LLM_EXTRA_BODY`. Without it Lightning spent a 64-token budget on visible reasoning and returned no JSON; with it the probe reply took 5 tokens.
   - `max_tokens = 256` for classifier calls. This is headroom over the 5-token probe reply plus a bounded `span`; it was not tuned on data. A reply that stops at the cap (`finish_reason=length`) is an error, scored pessimistically under Amendment 3.5.
   - JSON mode (`response_format: {"type": "json_object"}`). The probe showed Lightning returns valid JSON with it. The reply must still pass strict `{verdict, family, span}` parsing; any parse failure is an error, never benign.
   - Temperature 0 (unchanged).
2. **Changes after the kill run.** Any change to these settings, the model, the endpoint or the prompt after the kill run is a new experiment, reported separately. It does not revive the original verdict.
3. **Unverified, stated now.** Whether Nebius Token Factory accepts `chat_template_kwargs.enable_thinking`, and whether its Nemotron 3.5 Lightning serves the same weights as build.nvidia, are not verified (no Nebius key has been used yet). If this is not confirmed by 2026-10-06, the contingency in Amendment 1.3 applies unchanged: the kill test runs on build.nvidia, the Token Factory run is a separate re-measurement, and the 2026-10-09 date does not move.

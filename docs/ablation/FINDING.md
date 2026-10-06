# Dev ablation finding

**Status:** Dev results final; kill-rule verdict to be recorded 2026-10-09 per the ADR.

## Design
Pre-declaration `a1d5865`, cap addendum `659803d` (cap 1,100 calls; 1,055 used). Arms A0 (frozen prompt), A1 (A0 minus the
tie-breaker), A2 (span-extraction reply, verdict computed in code). Model: Nemotron-3 Ultra on Nebius Token Factory,
temperature 0. Dev items only, one run per arm. Primary convention: UNSURE counts as attack. Source: `results.md`.

## Results (Wilson 95% in brackets)
| arm | false positives /50 | tool_description detections /253 | tool_result detections /48 |
|---|---|---|---|
| A0 | 7 (7-26%) | 238 (90-96%) | 45 (83-98%) |
| A1 | 7 (7-26%) | 237 (90-96%) | 44 (80-97%) |
| A2 | 1 (0-10%) | 249 (96-99%) | 22 (33-60%) |

Dev bar: at most 4/50 false positives and at least 85% detection in each channel. No arm meets it.

## Findings
- A1 changed nothing on false positives (7/50 to 7/50), so the tie-breaker was not the cause. A1 removed two sentences as
  one contiguous deletion.
- A2 cut false positives to 1/50, but tool_result detection fell to 22/48. Cause [inferred]: not verified, because raw
  replies were not stored.
- tool_description detection is measured on attack-only rows, so it says nothing about specificity in that channel.

## Conclusion
Text-only single-pass classification did not satisfy both gates under pre-registration.

## Limitations
- No benign counterpart for the MCPTox attack rows. The only benign rows tagged tool_description are 20 hand-written
  quoting items.
- A2 raw replies were not stored (only UNSURE replies were).
- Benign n=50 is too small to check the ADR false-positive gate (Wilson upper bound 7% on 200 items); A2's upper bound is 10%.
- Single run per arm. Ultra only, not the pre-registered kill model. Dev only.

## Next
Kill rule per ADR on 2026-10-09. Held-out not run. Fallback is Witness-or-Redact PRs.

# MCP Signature Firewall

A proxy between an AI agent and its MCP servers that screens tool text for attacks. An LLM judges text the first time; confirmed attacks are stored so later variants are caught without another LLM call. The project exists to measure how far that cuts LLM calls without hurting detection.

## Language

### Text under inspection

**Tool description**:
The natural-language text an MCP server publishes to describe one of its tools.
_Avoid_: Tool metadata, manifest

**Tool result**:
The text an MCP server returns after a tool call.
_Avoid_: Tool output, response

**Attack**:
Adversarial text in a tool description or tool result that tries to steer the agent.
_Avoid_: Injection, poisoning, exploit

**Family**:
A labeled group of attacks sharing one technique.
_Avoid_: Category, class, type

**Hard negative**:
Benign text that quotes or discusses attacks, such as a security blog or an issue containing "ignore previous instructions".
_Avoid_: Benign sample, false-positive bait

**Quoting slice**:
The hard negatives written to quote or discuss attacks; the only slice that gates the kill rule.
_Avoid_: Hard-negative set, benign set

### Judging

**Verdict**:
The LLM classifier's answer for one piece of text: attack or benign, with a family.
_Avoid_: Prediction, label, score

**Signature**:
A stored record of one confirmed attack, used to recognise later variants without an LLM call.
_Avoid_: Spacer, fingerprint, rule

**Signature library**:
The collection of all signatures.
_Avoid_: Spacer library, attack database

**Call rate**:
The share of screened texts that needed an LLM verdict.
_Avoid_: LLM usage, cache miss rate

### Evaluation

**Held-out family**:
A family kept out of the dev set and out of every signature until the final measurement.
_Avoid_: Test family, unseen attack

**Dev set**:
The data used to tune thresholds and prompts.
_Avoid_: Validation set, training set

**Frozen set**:
The data used only for the final measurement, never tuned on.
_Avoid_: Test set, holdout

**Kill rule**:
The pre-registered pass or fail condition, set before any result, that decides whether the project continues.
_Avoid_: Success criteria, target

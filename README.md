# MCP Signature Firewall

> **Status: work in progress.** No results yet. The evaluation protocol was pre-registered before any data existed;
> see [docs/adr/0001-pre-registered-kill-rule.md](docs/adr/0001-pre-registered-kill-rule.md).

A proxy between an AI agent and its MCP servers that screens tool text for attacks. An LLM judges text the first time;
confirmed attacks are stored as signatures so later variants can be recognised without another LLM call.

The claim is deliberately narrow: this is a **measured cost and latency optimizer for an LLM attack classifier**.
It is not a promise to block prompt injection. Vocabulary is defined in [CONTEXT.md](CONTEXT.md).

Licence: Apache-2.0.

# Augur Documentation

Augur is a calibrated consensus-velocity detector for prediction markets. It reads price and volume from Polymarket and Kalshi, detects statistically significant changes in a bounded set of high-liquidity, anticipated-event markets, and emits structured events that downstream agents and human analysts can consume. It does not trade, does not predict outcomes, and does not generate causal narratives.

## What This Documentation Is

This tree is the authoritative description of Augur's design, scope, contracts, and methodology. File order in directories is not significant. Reading order is defined here in this index. Every term used anywhere is defined in `foundations/glossary.md`. Every data contract is in `contracts/`. Every algorithmic and statistical decision is in `methodology/`. The architecture is in `architecture/`. Risk and moat analysis is in `strategy/`. Worked examples are in `examples/`. Unresolved decisions are in `open-questions.md`.

## Reading Order — New Reader

Read these in order to build a complete mental model:

1. `foundations/overview.md` — what Augur is, in one page
2. `foundations/non-goals.md` — what Augur is not
3. `foundations/glossary.md` — vocabulary
4. `foundations/pitch.md` — outward-facing case
5. `architecture/system-design.md` — full system architecture
6. `methodology/calibration-methodology.md` — how confidence is computed
7. `methodology/manipulation-taxonomy.md` — what manipulation flags mean
8. `examples/positive-paths.md` — concrete value examples
9. `examples/negative-paths.md` — failure-mode examples
10. `strategy/risks-and-mitigations.md` — risk register
11. `strategy/moat-thesis.md` — defensibility analysis
12. `open-questions.md` — unresolved decisions with current best answers

## Reading Order — Implementer

Read these before writing or modifying any code:

1. `contracts/schema-and-versioning.md` — every data contract
2. `contracts/consumer-registry.md` — closed `ConsumerType` enum
3. `methodology/calibration-methodology.md` — confidence pipeline
4. `methodology/labeling-protocol.md` — ground-truth definition
5. `methodology/manipulation-taxonomy.md` — manipulation signatures
6. `architecture/system-design.md` — layer-by-layer architecture
7. `architecture/adaptive-polling-spec.md` — polling state machine
8. `architecture/deduplication-and-storms.md` — signal merge algorithm
9. `architecture/storage-and-scaling.md` — storage architecture and migration triggers

## Group Index

| Group               | Purpose                                               |
| ------------------- | ----------------------------------------------------- |
| `foundations/`      | Project framing, scope, vocabulary, outward case      |
| `contracts/`        | Data schemas and registries that bind layers together |
| `methodology/`      | Statistical, algorithmic, and process methodology     |
| `architecture/`     | System architecture, storage, polling, signal merging |
| `strategy/`         | Risk register and defensibility analysis              |
| `examples/`         | Worked positive-path and negative-path examples       |
| `open-questions.md` | Unresolved decisions with current best answers        |

## Conventions

- Cross-references use relative paths. Same-group: `./file.md`. Across groups: `../group/file.md`. Top level: `../open-questions.md`.
- File names are slugs. No numeric prefixes. Order lives here, not in filenames.
- The schema in `contracts/schema-and-versioning.md` is canonical. Any field used in any other doc must match it exactly.
- The `ConsumerType` enum in `contracts/consumer-registry.md` is closed. Any `actionable_for` value used anywhere must be a member.
- Augur reports facts. It does not synthesize causal narratives. Any prose claiming to know why a market moved does not belong in this documentation or in any output Augur produces.

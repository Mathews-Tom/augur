# Open Questions

Unresolved decisions about Augur's positioning, sourcing, and roadmap. Each entry has the current best answer; entries are revisited as evidence accumulates.

---

## Open-Source vs Product Split

**Question.** Which parts of Augur should be open-source and which should be proprietary?

**Current best answer.** The signal extraction code (detectors, manipulation detector, context assembler) and the schema definitions should be open-source. Open-sourcing the schema is necessary for it to become a de-facto standard for downstream agent integration; open-sourcing the detector code defends against the criticism that the algorithms are not novel (they are not, and pretending otherwise is a marketing weakness). The labeled corpus, the per-market reliability curves, and the curated taxonomy should remain proprietary because they are the actual moat per `./strategy/moat-thesis.md`.

**What would change the answer.** Evidence that consumers will only adopt the schema if a managed service backs it; evidence that an open-source detector layer attracts contributors who improve the calibration methodology faster than a closed team can.

---

## How to Source the Labeled Corpus Efficiently

**Question.** The labeling protocol in `./methodology/labeling-protocol.md` requires double-labeled events from a curated source set. Building this corpus by hand is slow. Is there a faster path?

**Current best answer.** No faster path that preserves the protocol's quality. The protocol's two-source verification, manual market association, and category assignment are the discipline that makes the corpus a moat; bypassing them produces volume without quality. Phase 2 builds the labeling pipeline as a tool that minimizes annotator effort within the protocol but does not shortcut it.

**Possible future paths.** (1) Active learning: model-suggested candidate events that annotators verify rather than annotate from scratch. (2) Source set expansion to include non-English wire services with appropriate annotators. (3) Crowd-sourced labeling with quality controls (similar to academic dataset construction). All deferred until Phase 6 minimum.

---

## Which Platforms to Add After Polymarket and Kalshi

**Question.** The architecture supports additional platforms via the poller interface. Which to add first?

**Current best answer.** Three candidates ranked by strategic value:

1. A non-US-regulated platform (e.g., a European event-contract exchange when one reaches sufficient liquidity) — diversifies the regulatory risk per the Polymarket offshore-status entry in `./strategy/risks-and-mitigations.md`.
2. Manifold Markets — adds breadth on long-tail topics, though liquidity is too thin for most signal types and would primarily extend the watchlist for cross-market context, not for primary signal extraction.
3. A futures-style derivative venue with event contracts (e.g., CME's event futures if expanded) — adds depth and cross-references between Augur and traditional futures markets.

**What would change the answer.** Specific platform launches with material liquidity; specific regulatory actions reducing access to current platforms.

---

## When to Graduate from Classical Detectors to Learned Detectors

**Question.** The Phase 1 detectors are classical (BOCPD, CUSUM, EWMA, Spearman). When does it make sense to add learned detectors (e.g., transformer-based anomaly detectors trained on the labeled corpus)?

**Current best answer.** Not before 18 months of corpus accumulation. Learned detectors require a labeled corpus large enough to train without overfitting; estimates suggest at least 5,000 labeled events with balanced category coverage are needed for a transformer-based detector to outperform the classical baselines on calibrated precision. At Augur's expected event volume, this is roughly 18 to 24 months of operation. Before then, learned detectors will memorize idiosyncrasies of the limited corpus and fail to generalize.

**What would change the answer.** Faster corpus growth (e.g., via additional source adapters or platform expansion); availability of pretrained event-detection models that transfer well with limited fine-tuning.

---

## How to Monetize Without Becoming a Manipulation Amplifier

**Question.** The most obvious monetization paths (signal feed for traders, news-tip subscription for desks) increase the value of triggering an Augur signal for a manipulator. How does the system avoid becoming a manipulation amplification vector?

**Current best answer.** Three structural defenses:

1. **Conservative manipulation flagging by default.** The signature catalog in `./methodology/manipulation-taxonomy.md` is conservative but not zero-recall. Consumer suppression defaults for news desks exclude the most amplification-prone flag combinations.
2. **Calibrated confidence as a public-facing metric.** Consumers see and learn the meaning of calibrated confidence. A signal carrying low confidence and any manipulation flag is unlikely to be amplified by a literate consumer.
3. **Avoid trading-adjacent monetization.** Do not sell to consumers whose business model is amplification (e.g., low-quality news sites, content farms). Limit consumer onboarding to entities whose editorial discipline reduces the risk of misuse.

**What would change the answer.** Evidence that an amplification incident occurred and was traceable to Augur output; evidence that the recommended consumer suppression policies are not adopted in practice; emergence of consumer types not anticipated in the registry.

---

## Should the LLM Formatter Be Removed Entirely?

**Question.** The LLM formatter is gated, opt-in, and forbidden-token-checked. Even with these constraints, residual coherence-manufacturing risk remains per `./examples/negative-paths.md`. Should the LLM formatter exist at all?

**Current best answer.** The LLM formatter exists because human-facing channels (Slack briefs, dashboard summaries) benefit from prose. The deterministic Markdown formatter produces functional but stilted output that human readers find harder to scan. Removing the LLM formatter entirely would either degrade the human-channel experience or push consumers to wrap Augur with their own LLM, where Augur loses control over the forbidden-token check. Keeping the formatter inside Augur with strong constraints is the lesser harm.

**What would change the answer.** Evidence that the deterministic Markdown formatter is sufficient for human-channel adoption; evidence that the forbidden-token check is regularly bypassed by phrasings not in the closed list; a single high-profile incident attributing harm to an LLM-rendered Augur brief.

---

## Severity Banding — Should `medium` Tier Be Routable to More Consumers?

**Question.** The severity derivation in the formatter spec produces `low / medium / high`. Most agent consumers receive only `high` by default. Should `medium` be more broadly routed?

**Current best answer.** No. The current routing concentrates consumer attention on the highest-precision signals. Broadening `medium` routing increases noise faster than it increases value at current calibration quality. Once the labeled corpus produces tighter reliability curves (estimated 12+ months), `medium` routing can be reconsidered.

**What would change the answer.** Tighter reliability curves shifting the empirical precision of `medium` signals into the band consumers find useful; consumer feedback that they want broader coverage at the cost of precision.

---

## Should Augur Track Resolution Outcomes Explicitly?

**Question.** Each signal references a market that eventually resolves. Should Augur track resolution outcomes as a first-class signal-evaluation dataset, separate from the labeled-event corpus?

**Current best answer.** Yes, but as a secondary dataset, not as a calibration source. Resolution outcomes answer "did the market's prediction prove correct," which is different from "did Augur's signal correspond to a newsworthy event." The labeled-event corpus is the calibration source per `./methodology/labeling-protocol.md`. The resolution-outcome dataset is useful for marketing claims ("Augur signals on markets that resolved YES had X% mean confidence") and for future learned-detector training, but it does not replace the event corpus.

**What would change the answer.** Evidence that consumers value resolution-outcome statistics more than newsworthy-event precision; emergence of a learned detector that uses resolution outcomes as training labels and outperforms the classical baseline.

---

## How Should Augur Handle Duplicate Markets Across Platforms?

**Question.** The same underlying event may have markets on both Polymarket and Kalshi (e.g., Fed rate decisions). Should Augur treat these as a single logical market, or as related-but-distinct markets?

**Current best answer.** Related-but-distinct, with explicit cross-platform taxonomy edges. Treating duplicates as a single market would mask important information: the two markets often diverge in price, and the divergence is itself a signal (one platform's participants may be acting on different information than the other's). The cross-market divergence detector handles this directly when the taxonomy edge is configured.

**What would change the answer.** Evidence that consumers are confused by receiving signals on two platforms for "the same" event; emergence of a consumer use case that explicitly wants cross-platform-merged signals.

---

## Coverage Expansion: Sports Markets

**Question.** Sports outcome contracts represent a large fraction of Polymarket and Kalshi volume but are explicitly out of scope per `./foundations/non-goals.md`. Should Augur reconsider?

**Current best answer.** Not at this stage. Sports markets do not match Augur's intelligence-product framing; the consumer base for sports event signals is fundamentally different from the consumer base for macro, geopolitical, and regulatory signals. A separate product or a distinct configuration of Augur could address sports markets, but mixing them into the core feed dilutes the product.

**What would change the answer.** Evidence that the existing consumer set wants sports coverage; emergence of a separable distribution channel for sports signals that does not contaminate the macro/geopolitical/regulatory feed.

# Public Workflows

Step-by-step public workflows for each Birdeye Skills skill — **what the skill does,
which Birdeye endpoint it calls, what it checks, and in which mode**.

These are the *public* counterparts of the private engine workflow docs. The exact
formulas, ramp thresholds and model assets stay in the closed engine; here you get the
concept, the step order, the endpoint behind each step, the scoring weights at a high
level, the CU cost and how to read the output.

> Need the command surface instead? See the root [`README.md`](../README.md) and each
> [`skills/<name>/SKILL.md`](../skills/).

| Skill | Workflow | Answers |
|---|---|---|
| `token-dd-score` | [token-dd-score-workflow.md](token-dd-score-workflow.md) | Should I trust this token? 0–100 + A+..F rating |
| `trending-list` | [trending-list-workflow.md](trending-list-workflow.md) | What is hot right now? |
| `price-surge` | [price-surge-workflow.md](price-surge-workflow.md) | What is surging in my market-cap band, risk-screened? |
| `wallet-score` | [wallet-score-workflow.md](wallet-score-workflow.md) | Wallet alpha + copy-tradeability |
| `wallet-style` | [wallet-style-workflow.md](wallet-style-workflow.md) | Scalper or swing trader? |
| `kline-pattern` | [kline-pattern-workflow.md](kline-pattern-workflow.md) | Candlestick / chart pattern |
| `token-trending-score` | [token-trending-score-workflow.md](token-trending-score-workflow.md) | How hot / trending is a token? |
| `junk-predict` | [junk-predict-workflow.md](junk-predict-workflow.md) | Is this token junk / a scam / dust? |

Each workflow follows the same shape:

1. **At a glance** — the pipeline as a table (step · endpoint · what it checks · mode · CU).
2. **Step by step** — what each step reads from the API and what it decides.
3. **Scoring** — the weighted model at a high level.
4. **Output** — how to read the response.
5. **Cost** — the CU budget.
6. **Errors** — the shared error map.

All skills share the same cost footer (`⚡CU: <total> (<breakdown>)`) and the same
error codes (`[E401]` / `[E403]` / `[E429]` / `[E500]`).

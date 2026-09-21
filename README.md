# Bedrock Cost Guard

Know what a Bedrock run will cost **before** you start it, and know what it actually cost when it finishes.

Written by **Adam Tate**. Published here so every EFS project uses the same guard instead of each person
rediscovering their spend after the fact.

> **Why this exists.** EFS runs Bedrock inference across shared AWS accounts that also pay real bills. A
> benchmark that looks like "a few hundred calls" can be five thousand calls and tens of dollars by the time
> it finishes, and nobody notices until an alert fires. This tool puts a number in front of you first, then
> logs every call's real token usage so the number at the end is measured, not guessed.

## What it does

| | |
|---|---|
| **Estimates first** | `plan()` prints the projected cost for a run and asks you to confirm before the first call to that model |
| **Refuses unpriced models** | If a model has no price in `prices.json`, it will not run. No silent guessing |
| **Logs real usage** | Every call appends the actual input/output tokens from the API response to `usage_log.jsonl` |
| **Caps spend twice** | A per-session cap you pass in, and a total cap across all sessions (default $100) in `prices.json` |
| **Reports per session** | `report` shows calls, tokens and dollars by session and model, with a grand total |

## Install

```bash
pip install boto3
git clone https://github.com/efsnetworksinc/bedrock-cost-guard.git
cd bedrock-cost-guard
cp prices.example.json prices.json     # then fill in prices, see below
```

You need AWS credentials that can call `bedrock-runtime` in **us-east-1**. Other regions are blocked by
policy — pass a different one only if you have been told to.

## Prices: the part you must do yourself

`prices.json` is the source of truth and it is **not** shipped filled in. Copy the example, then enter USD
per 1M tokens for every model you plan to call, from <https://aws.amazon.com/bedrock/pricing/>, along with
the date you read them.

```json
{
  "price_date": "2026-09-18",
  "total_cap_usd": 100,
  "models": {
    "openai.gpt-oss-120b-1:0": { "in_per_mtok": 0.15, "out_per_mtok": 0.6 },
    "global.anthropic.claude-sonnet-4-6": { "in_per_mtok": 3.0, "out_per_mtok": 15.0 }
  }
}
```

`null` prices mean the guard refuses that model. That is deliberate — an unpriced model is an unbounded run.

**`prices.reference.json`** in this repo holds the 32 models EFS priced on **2026-09-18**, as a starting
point. Copy what you need, but check the current page before you trust it. AWS changes prices and nothing
here updates automatically.

## Use it as a library

This is the way it is meant to be used. Route every Bedrock call through the guard:

```python
from bedrock_cost_guard import Guard

g = Guard(session="ocelot-benchmark-01", cap_usd=25, profile="efs")
g.plan("openai.gpt-oss-120b-1:0", calls=850, in_tokens=3000, out_tokens=600)
text = g.converse("openai.gpt-oss-120b-1:0", "prompt here", max_tokens=600)
```

`plan()` prints this and waits:

```
[cost guard] openai.gpt-oss-120b-1:0: 850 calls x (3000 in + 600 out) tokens
  estimate        $0.69
  session so far  $0.00 of $25.00 cap  (ocelot-benchmark-01)
  all sessions    $46.42 of $100.00 cap
  proceed? [y/N]
```

Call `plan()` once per model per session. `converse()` refuses any model that has not been planned, and the
whole session stops with an error once either cap is reached.

Pass `assume_yes=True` only for unattended runs you have already sized.

## Use it from the command line

```bash
# What would this cost?
python bedrock_cost_guard.py estimate --model openai.gpt-oss-120b-1:0 \
    --calls 850 --in-tokens 3000 --out-tokens 600

# What has it cost so far?
python bedrock_cost_guard.py report
python bedrock_cost_guard.py report --session ocelot-benchmark-01
```

## Reading the report

Real output from the Ocelot model benchmark on 2026-09-18:

```
session                      model                              calls     in tok    out tok       usd
nyt1010-gpt-6-astra          global.openai.gpt-6-astra            131      17030      22433      5.35
nyt1010-grok-4.6             global.xai.grok-4.6                  128     323418     338644      2.74
nyt1010-sonnet-4.6           global.anthropic.claude-sonnet-4-6   147      76244      94710      2.96
nyt1010-kimi-k2              moonshot.kimi-k2-thinking            127     400915     402723      1.25
nyt1010-gpt-oss-120b         openai.gpt-oss-120b-1:0              140     465902     142534      0.16
TOTAL                                                            5775                           46.42
```

Two things that run is worth knowing for:

- **5,775 calls and $46.42** for two articles across fourteen models. Multi-model benchmarks are much bigger
  than they feel while you are setting them up.
- The per-call **orchestration overhead is real**. Every `nyt1010-*` session also shows Sonnet calls — the
  agent pipeline driving the run. On some models that overhead cost more than the model under test.

## Cost tracking is not the same as the AWS console

EFS also has a Bedrock usage tracker that estimates at a flat rate per call. On the same day, the tracker
read roughly $0.01/call while this guard measured **$46.42 across 5,775 calls** from real token counts.
Flat-rate call counting and token-accurate pricing will not agree, and the gap grows with long prompts.
Use this guard's number when you need to answer "what did we actually spend".

## Files

| File | What it is |
|---|---|
| `bedrock_cost_guard.py` | The guard. Library (`Guard`) plus `estimate` and `report` commands |
| `prices.example.json` | Empty template. Copy to `prices.json` and fill in |
| `prices.reference.json` | 32 models priced on 2026-09-18, as a starting point. Verify before use |
| `usage_log.jsonl` | Created on first run. One JSON line per call. Gitignored |

## Rules it enforces

1. **No price, no run.** Prices come from the AWS pricing page, entered by a human, with a date.
2. **`plan()` must be confirmed** before the first call to a model in a session.
3. **Every call is logged** with the token counts the API reported, not estimates.
4. **The session stops** at `cap_usd`; **everything stops** at `total_cap_usd`.
5. **us-east-1 only.** Other regions are blocked by policy.
6. **Post your `report` output** in the project thread when a run finishes.

## Limits worth knowing

- The log is a **local file**. Two people on two machines each get their own `$100`; the cap is not
  org-wide. For shared budgets, agree the split up front.
- `converse()` covers the Converse API. Streaming, batch and image generation are not wrapped — if you use
  those, the spend will not appear in the log.
- Cost is computed from **on-demand** prices. Provisioned throughput and batch discounts are not modelled.
- Some models need a commercial agreement with AWS Sales before they are callable at all. An
  `AccessDeniedException` is an entitlement problem, not a pricing one.

## Credits

Written by Adam Tate. Published to the EFS org by Milan Varghese at Evan's request, 21 Sep 2026.

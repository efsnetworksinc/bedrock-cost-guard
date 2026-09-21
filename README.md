# Bedrock Cost Guard

Know what a Bedrock run will cost **before** you start it, and what it actually cost when it finishes.

Written by **Adam Tate**.

A benchmark that feels like "a few hundred calls" turns out to be several thousand calls and tens of dollars,
and on a shared AWS account nobody notices until an alert fires.

## What it does

- **Estimates first.** `plan()` prints the projected cost and waits for a y/N before the first call.
- **Refuses unpriced models.** No price in `prices.json`, no run. Nothing is guessed.
- **Logs real usage.** Every call's actual token counts go to `usage_log.jsonl`.
- **Caps spend twice.** A per-session cap you pass in, and a total cap across sessions (default $100).
- **Reports.** Calls, tokens and dollars by session and model.

## Install

```bash
pip install boto3
git clone https://github.com/efsnetworksinc/bedrock-cost-guard.git
cd bedrock-cost-guard
cp prices.example.json prices.json
```

Needs AWS credentials for `bedrock-runtime` in **us-east-1**.

## Prices

`prices.json` is the source of truth and ships empty. Fill in USD per 1M tokens for every model you will
call, from <https://aws.amazon.com/bedrock/pricing/>, with the date you read them.

```json
{
  "price_date": "2026-09-18",
  "total_cap_usd": 100,
  "models": {
    "openai.gpt-oss-120b-1:0": { "in_per_mtok": 0.15, "out_per_mtok": 0.6 }
  }
}
```

`null` means the guard refuses that model — an unpriced model is an unbounded run.

`prices.reference.json` has 32 models priced on 2026-09-18 as a starting point. Verify before trusting it.

## Use

```python
from bedrock_cost_guard import Guard

g = Guard(session="benchmark-01", cap_usd=25, profile="default")
g.plan("openai.gpt-oss-120b-1:0", calls=850, in_tokens=3000, out_tokens=600)
text = g.converse("openai.gpt-oss-120b-1:0", "prompt here", max_tokens=600)
```

`plan()` runs once per model per session; `converse()` refuses anything unplanned. `assume_yes=True` for
unattended runs you have already sized.

```bash
python bedrock_cost_guard.py estimate --model MODEL_ID --calls 850 --in-tokens 3000 --out-tokens 600
python bedrock_cost_guard.py report [--session NAME]
```

## Files

| File | |
|---|---|
| `bedrock_cost_guard.py` | The guard: `Guard` class, `estimate` and `report` commands |
| `prices.example.json` | Empty template. Copy to `prices.json` |
| `prices.reference.json` | 32 models priced 2026-09-18. Verify before use |
| `usage_log.jsonl` | One JSON line per call. Created on first run, gitignored |

## Worth knowing

- **The log is a local file.** Two people on two machines each get their own $100 — the cap is not shared.
- **Converse API only.** Streaming, batch and image generation are not wrapped, so that spend never appears.
- **On-demand prices only.** Provisioned throughput and batch discounts are not modelled.
- **Orchestration counts.** If an agent pipeline drives the run, its own calls land in the same session and
  can cost more than the model under test.
- **Flat per-call dashboards will not agree** with token-accurate pricing, and the gap grows with long
  prompts. This number comes from what the API reported.
- `AccessDeniedException` is an entitlement problem, not a pricing one — some models need an agreement with
  AWS Sales first.

## Credits

Written by Adam Tate at EFS Networks. Packaged and documented by Milan Varghese, September 2026.

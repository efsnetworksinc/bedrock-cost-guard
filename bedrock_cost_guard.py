#!/usr/bin/env python3
"""Bedrock cost guard: estimate before you run, log what each session actually cost.

Usage as a library (recommended - route every Bedrock call through it):

    from bedrock_cost_guard import Guard
    g = Guard(session="benchmark-01", cap_usd=25, profile="default")
    g.plan("openai.gpt-oss-120b-1:0", calls=850, in_tokens=3000, out_tokens=600)   # prints estimate, asks y/N
    text = g.converse("openai.gpt-oss-120b-1:0", "prompt here", max_tokens=600)

CLI:
    bedrock_cost_guard.py estimate --model ID --calls N --in-tokens N --out-tokens N
    bedrock_cost_guard.py report                # cost per session + grand total from the log
    bedrock_cost_guard.py report --session NAME

Rules it enforces:
  * No price, no run. Prices live in prices.json (USD per 1M tokens) and YOU fill them in from
    https://aws.amazon.com/bedrock/pricing/ with the date you read them. Nothing is guessed.
  * plan() must be confirmed before the first call for a model in a session.
  * Every call's real token usage (from the API response) is appended to usage_log.jsonl.
  * The session stops with an error once logged spend reaches cap_usd.
  * The total across ALL sessions stops at total_cap_usd in prices.json (default 100).
"""
import argparse, json, os, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRICES = Path(os.environ.get("BCG_PRICES", HERE / "prices.json"))
LOG = Path(os.environ.get("BCG_LOG", HERE / "usage_log.jsonl"))


class CostGuardError(RuntimeError):
    pass


def load_prices():
    if not PRICES.exists():
        raise CostGuardError(f"{PRICES} missing. Copy prices.example.json and fill in real prices.")
    d = json.loads(PRICES.read_text())
    return d.get("models", {}), float(d.get("total_cap_usd", 100))


def price_for(model):
    models, _ = load_prices()
    p = models.get(model)
    if not p or p.get("in_per_mtok") is None or p.get("out_per_mtok") is None:
        raise CostGuardError(f"No price for {model} in {PRICES}. Add it from the Bedrock pricing page first.")
    return float(p["in_per_mtok"]), float(p["out_per_mtok"])


def cost(model, in_tok, out_tok):
    pi, po = price_for(model)
    return in_tok / 1e6 * pi + out_tok / 1e6 * po


def read_log():
    if not LOG.exists():
        return []
    return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]


def spent(session=None):
    return sum(r["usd"] for r in read_log() if session is None or r["session"] == session)


class Guard:
    def __init__(self, session, cap_usd, profile=None, region="us-east-1", assume_yes=False):
        self.session, self.cap, self.assume_yes = session, float(cap_usd), assume_yes
        self.approved = set()
        import boto3
        self.client = boto3.Session(profile_name=profile, region_name=region).client("bedrock-runtime")

    def plan(self, model, calls, in_tokens, out_tokens):
        est = cost(model, calls * in_tokens, calls * out_tokens)
        _, total_cap = load_prices()
        s, t = spent(self.session), spent()
        print(f"\n[cost guard] {model}: {calls} calls x ({in_tokens} in + {out_tokens} out) tokens")
        print(f"  estimate        ${est:,.2f}")
        print(f"  session so far  ${s:,.2f} of ${self.cap:,.2f} cap  ({self.session})")
        print(f"  all sessions    ${t:,.2f} of ${total_cap:,.2f} cap")
        if s + est > self.cap or t + est > total_cap:
            raise CostGuardError("Estimate would exceed a cap. Shrink the run or get the cap raised in writing.")
        if not self.assume_yes and input("  proceed? [y/N] ").strip().lower() != "y":
            raise CostGuardError("Not confirmed.")
        self.approved.add(model)
        return est

    def converse(self, model, prompt, max_tokens=512, system=None, **kw):
        if model not in self.approved:
            raise CostGuardError(f"Call plan() for {model} in this session before invoking it.")
        _, total_cap = load_prices()
        if spent(self.session) >= self.cap or spent() >= total_cap:
            raise CostGuardError("Cap reached. Stopping.")
        args = dict(modelId=model, messages=[{"role": "user", "content": [{"text": prompt}]}],
                    inferenceConfig={"maxTokens": max_tokens, **kw})
        if system:
            args["system"] = [{"text": system}]
        r = self.client.converse(**args)
        u = r["usage"]
        usd = cost(model, u["inputTokens"], u["outputTokens"])
        with LOG.open("a") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": self.session, "model": model,
                                "in": u["inputTokens"], "out": u["outputTokens"], "usd": round(usd, 6)}) + "\n")
        return "".join(b.get("text", "") for b in r["output"]["message"]["content"])


def report(session=None):
    rows = [r for r in read_log() if session is None or r["session"] == session]
    agg = {}
    for r in rows:
        k = (r["session"], r["model"])
        a = agg.setdefault(k, [0, 0, 0, 0.0])
        a[0] += 1; a[1] += r["in"]; a[2] += r["out"]; a[3] += r["usd"]
    print(f"{'session':28} {'model':34} {'calls':>6} {'in tok':>10} {'out tok':>10} {'usd':>9}")
    for (s, m), a in sorted(agg.items()):
        print(f"{s:28} {m:34} {a[0]:>6} {a[1]:>10} {a[2]:>10} {a[3]:>9.2f}")
    print(f"{'TOTAL':28} {'':34} {len(rows):>6} {'':>10} {'':>10} {sum(r['usd'] for r in rows):>9.2f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate")
    e.add_argument("--model", required=True); e.add_argument("--calls", type=int, required=True)
    e.add_argument("--in-tokens", type=int, required=True); e.add_argument("--out-tokens", type=int, required=True)
    rp = sub.add_parser("report"); rp.add_argument("--session")
    a = ap.parse_args()
    try:
        if a.cmd == "estimate":
            print(f"${cost(a.model, a.calls * a.in_tokens, a.calls * a.out_tokens):,.2f}")
        else:
            report(a.session)
    except CostGuardError as x:
        sys.exit(f"cost guard: {x}")

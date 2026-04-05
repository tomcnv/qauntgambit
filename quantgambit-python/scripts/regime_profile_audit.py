#!/usr/bin/env python3
"""
Live regime/profile audit report.

What this script audits:
1) Recent decision events (selected profiles, rejection reasons, concentration)
2) Recent feature snapshots (market regime/session context distribution)
3) Per-profile eligibility across recent contexts by symbol:
   - rule pass rate (router hard filters)
   - env-eligible rate (after strategy disable rules)
   - env-blocked rate (profile passes but all strategies disabled)
   - average profile score and top-1 frequency

Outputs:
- Markdown report (human-readable)
- JSON report (machine-readable)

Usage example:
  ./venv/bin/python scripts/regime_profile_audit.py \
    --tenant-id 11111111-1111-1111-1111-111111111111 \
    --bot-id bf167763-fee1-4f11-ab9a-6fddadf125de \
    --hours 3 --feature-count 2500 --decision-count 4000
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from redis import Redis

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantgambit.deeptrader_core.profiles.profile_router import get_profile_router
from quantgambit.deeptrader_core.profiles.router_config import RouterConfig
from quantgambit.profiles.router import _build_context_vector
from quantgambit.strategies.disable_rules import enabled_strategies_for_symbol


def _stream_name(base: str, tenant_id: str, bot_id: str) -> str:
    return f"{base}:{tenant_id}:{bot_id}"


def _decode(v: Any) -> Any:
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return v


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def _resolve_distance_to_poc_bps(features: Dict[str, Any], market_context: Dict[str, Any]) -> float:
    """
    Resolve distance-to-POC in bps from mixed legacy/canonical payloads.

    Priority:
    1) Explicit distance_to_poc_bps field (features or market_context)
    2) Legacy signed price distance_to_poc converted using price baseline
    3) price - point_of_control converted to bps
    """
    explicit_bps = market_context.get("distance_to_poc_bps")
    if explicit_bps is None:
        explicit_bps = features.get("distance_to_poc_bps")
    explicit_bps_f = _safe_float(explicit_bps, default=float("nan"))
    if not math.isnan(explicit_bps_f):
        return explicit_bps_f

    price = _safe_float(market_context.get("price"), default=float("nan"))
    if math.isnan(price):
        price = _safe_float(features.get("price"), default=float("nan"))
    if math.isnan(price) or price <= 0:
        return 0.0

    legacy_dist = market_context.get("distance_to_poc")
    if legacy_dist is None:
        legacy_dist = features.get("distance_to_poc")
    legacy_dist_f = _safe_float(legacy_dist, default=float("nan"))
    if not math.isnan(legacy_dist_f):
        return (legacy_dist_f / price) * 10000.0

    poc = market_context.get("point_of_control")
    if poc is None:
        poc = features.get("point_of_control")
    poc_f = _safe_float(poc, default=float("nan"))
    if math.isnan(poc_f):
        return 0.0
    return ((price - poc_f) / price) * 10000.0


def _utc_from_ts(ts: Any) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except Exception:
        return None


def _quantile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * q))))
    return ordered[idx]


def _simplify_reason(reason: str) -> str:
    if ":" in reason:
        return reason.split(":", 1)[0].strip()
    return reason.strip()


def _parse_stream_events(redis: Redis, stream: str, count: int) -> List[dict]:
    rows = redis.xrevrange(stream, "+", "-", count=count)
    events: List[dict] = []
    for entry_id, fields in rows:
        decoded_fields: Dict[str, Any] = {_decode(k): _decode(v) for k, v in fields.items()}
        data_raw = decoded_fields.get("data")
        if not data_raw:
            continue
        try:
            obj = json.loads(data_raw)
        except json.JSONDecodeError:
            continue
        obj["_stream_id"] = _decode(entry_id)
        events.append(obj)
    return events


@dataclass
class ProfileAuditStats:
    samples: int = 0
    rule_pass: int = 0
    env_eligible: int = 0
    env_blocked: int = 0
    top1_env_eligible: int = 0
    score_sum: float = 0.0

    def to_dict(self) -> dict:
        avg_score = self.score_sum / self.rule_pass if self.rule_pass else 0.0
        return {
            "samples": self.samples,
            "rule_pass": self.rule_pass,
            "rule_pass_rate": round(self.rule_pass / self.samples, 4) if self.samples else 0.0,
            "env_eligible": self.env_eligible,
            "env_eligible_rate": round(self.env_eligible / self.samples, 4) if self.samples else 0.0,
            "env_blocked": self.env_blocked,
            "env_blocked_rate": round(self.env_blocked / self.samples, 4) if self.samples else 0.0,
            "top1_env_eligible": self.top1_env_eligible,
            "top1_rate": round(self.top1_env_eligible / self.samples, 4) if self.samples else 0.0,
            "avg_score_when_rule_pass": round(avg_score, 6),
        }


def _build_markdown_report(
    *,
    generated_at: datetime,
    args: argparse.Namespace,
    env_snapshot: Dict[str, Any],
    decision_summary: Dict[str, Any],
    context_summary: Dict[str, Any],
    profile_audit: Dict[str, Any],
    recommendations: List[str],
) -> str:
    lines: List[str] = []
    lines.append(f"# Regime/Profile Audit Report")
    lines.append("")
    lines.append(f"- Generated (UTC): `{generated_at.isoformat()}`")
    lines.append(f"- Tenant: `{args.tenant_id}`")
    lines.append(f"- Bot: `{args.bot_id}`")
    lines.append(f"- Window: last `{args.hours}`h")
    lines.append(f"- Decision samples: `{args.decision_count}`")
    lines.append(f"- Feature samples: `{args.feature_count}`")
    lines.append("")
    lines.append("## Runtime Config Snapshot")
    lines.append("")
    for k, v in env_snapshot.items():
        lines.append(f"- `{k}`: `{v}`")
    lines.append("")

    lines.append("## Decision Stream Summary")
    lines.append("")
    lines.append(f"- Decisions in window: `{decision_summary.get('decisions_in_window', 0)}`")
    lines.append(f"- Symbols observed: `{', '.join(decision_summary.get('symbols', [])) or 'none'}`")
    lines.append("")
    lines.append("### Selected Profile Mix")
    lines.append("")
    for symbol, top in decision_summary.get("selected_profiles_by_symbol", {}).items():
        lines.append(f"- `{symbol}`:")
        for p in top[:8]:
            lines.append(f"  - `{p['profile_id']}`: `{p['count']}` ({p['pct']}%)")
    lines.append("")
    lines.append("### Rejection Reasons")
    lines.append("")
    for symbol, top in decision_summary.get("rejection_reasons_by_symbol", {}).items():
        lines.append(f"- `{symbol}`:")
        for r in top[:8]:
            lines.append(f"  - `{r['reason']}`: `{r['count']}` ({r['pct']}%)")
    lines.append("")

    lines.append("## Feature/Regime Context Summary")
    lines.append("")
    for symbol, stats in context_summary.items():
        lines.append(f"### `{symbol}`")
        lines.append(f"- Samples: `{stats['samples']}`")
        lines.append(f"- Session mix: `{stats['session_mix']}`")
        lines.append(f"- Volatility regime mix: `{stats['volatility_mix']}`")
        lines.append(f"- Market regime mix: `{stats['market_regime_mix']}`")
        lines.append(
            f"- Rotation |abs| p50/p90: `{stats['rotation_abs_p50']:.3f}` / `{stats['rotation_abs_p90']:.3f}`"
        )
        lines.append(f"- ATR ratio p50/p90: `{stats['atr_ratio_p50']:.3f}` / `{stats['atr_ratio_p90']:.3f}`")
        lines.append(
            f"- Dist-to-POC bps p50/p90: `{stats['distance_to_poc_bps_p50']:.2f}` / `{stats['distance_to_poc_bps_p90']:.2f}`"
        )
        lines.append("")

    lines.append("## Profile Eligibility Audit")
    lines.append("")
    for symbol, data in profile_audit.items():
        lines.append(f"### `{symbol}`")
        lines.append(f"- Snapshot contexts audited: `{data['contexts_audited']}`")
        lines.append("- Top profiles by env-eligible rate (rule pass + enabled strategies):")
        for row in data["top_env_eligible_profiles"][:10]:
            lines.append(
                f"  - `{row['profile_id']}`: env-eligible `{row['env_eligible_rate']*100:.1f}%`, "
                f"top1 `{row['top1_rate']*100:.1f}%`, avg score `{row['avg_score_when_rule_pass']:.3f}`"
            )
        lines.append("- Most env-blocked profiles (pass rules but strategies disabled):")
        for row in data["top_env_blocked_profiles"][:8]:
            lines.append(
                f"  - `{row['profile_id']}`: blocked `{row['env_blocked_rate']*100:.1f}%` "
                f"({row['env_blocked']}/{row['samples']})"
            )
        lines.append("- Most common rule-fail reasons:")
        for reason, count in data["top_rule_fail_reasons"][:10]:
            lines.append(f"  - `{reason}`: `{count}`")
        lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    for rec in recommendations:
        lines.append(f"- {rec}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a full live regime/profile audit report.")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--hours", type=float, default=3.0, help="Lookback window in hours.")
    parser.add_argument("--decision-count", type=int, default=4000)
    parser.add_argument("--feature-count", type=int, default=3000)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    parser.add_argument("--output-prefix", default="/tmp/regime_profile_audit")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=float(args.hours))

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis = Redis.from_url(redis_url, decode_responses=False)

    decision_stream = _stream_name("events:decisions", args.tenant_id, args.bot_id)
    feature_stream = _stream_name("events:features", args.tenant_id, args.bot_id)

    decision_events = _parse_stream_events(redis, decision_stream, count=args.decision_count)
    feature_events = _parse_stream_events(redis, feature_stream, count=args.feature_count)

    # 1) Decision summary
    selected_profile_by_symbol: Dict[str, Counter] = defaultdict(Counter)
    rejection_by_symbol: Dict[str, Counter] = defaultdict(Counter)
    decisions_in_window = 0

    for evt in decision_events:
        payload = (evt.get("payload") or {}) if isinstance(evt, dict) else {}
        symbol = str(payload.get("symbol") or evt.get("symbol") or "").upper()
        if symbol not in symbols:
            continue
        ts = _utc_from_ts(evt.get("timestamp") or payload.get("timestamp"))
        if ts is None or ts < cutoff:
            continue
        decisions_in_window += 1
        profile_id = str(payload.get("profile_id") or "unknown")
        rejection_reason = str(payload.get("rejection_reason") or "none")
        selected_profile_by_symbol[symbol][profile_id] += 1
        rejection_by_symbol[symbol][rejection_reason] += 1

    decision_summary = {
        "decisions_in_window": decisions_in_window,
        "symbols": sorted(k for k in selected_profile_by_symbol.keys()),
        "selected_profiles_by_symbol": {},
        "rejection_reasons_by_symbol": {},
    }
    for symbol in symbols:
        sp = selected_profile_by_symbol.get(symbol, Counter())
        rp = rejection_by_symbol.get(symbol, Counter())
        sp_total = sum(sp.values()) or 1
        rp_total = sum(rp.values()) or 1
        decision_summary["selected_profiles_by_symbol"][symbol] = [
            {"profile_id": pid, "count": c, "pct": round((c / sp_total) * 100.0, 2)}
            for pid, c in sp.most_common()
        ]
        decision_summary["rejection_reasons_by_symbol"][symbol] = [
            {"reason": r, "count": c, "pct": round((c / rp_total) * 100.0, 2)}
            for r, c in rp.most_common()
        ]

    # 2) Build recent contexts from feature stream
    contexts_by_symbol: Dict[str, List[Tuple[dict, dict]]] = defaultdict(list)
    rotation_abs_vals: Dict[str, List[float]] = defaultdict(list)
    atr_ratio_vals: Dict[str, List[float]] = defaultdict(list)
    dist_poc_vals: Dict[str, List[float]] = defaultdict(list)
    session_mix: Dict[str, Counter] = defaultdict(Counter)
    vol_mix: Dict[str, Counter] = defaultdict(Counter)
    regime_mix: Dict[str, Counter] = defaultdict(Counter)

    for evt in feature_events:
        payload = (evt.get("payload") or {}) if isinstance(evt, dict) else {}
        symbol = str(payload.get("symbol") or evt.get("symbol") or "").upper()
        if symbol not in symbols:
            continue
        ts = _utc_from_ts(evt.get("timestamp") or payload.get("timestamp"))
        if ts is None or ts < cutoff:
            continue
        features = payload.get("features") or {}
        market_context = payload.get("market_context") or {}
        if not isinstance(features, dict) or not isinstance(market_context, dict):
            continue
        contexts_by_symbol[symbol].append((market_context, features))

        session_mix[symbol][str(market_context.get("session") or "unknown")] += 1
        vol_mix[symbol][str(market_context.get("volatility_regime") or "unknown")] += 1
        regime_mix[symbol][str(market_context.get("market_regime") or "unknown")] += 1

        rotation_abs_vals[symbol].append(abs(_safe_float(features.get("rotation_factor"))))
        atr_ratio_vals[symbol].append(_safe_float(features.get("atr_ratio")))
        dist_poc_vals[symbol].append(abs(_resolve_distance_to_poc_bps(features, market_context)))

    context_summary: Dict[str, Any] = {}
    for symbol in symbols:
        context_summary[symbol] = {
            "samples": len(contexts_by_symbol.get(symbol, [])),
            "session_mix": dict(session_mix[symbol].most_common()),
            "volatility_mix": dict(vol_mix[symbol].most_common()),
            "market_regime_mix": dict(regime_mix[symbol].most_common()),
            "rotation_abs_p50": _quantile(rotation_abs_vals[symbol], 0.5),
            "rotation_abs_p90": _quantile(rotation_abs_vals[symbol], 0.9),
            "atr_ratio_p50": _quantile(atr_ratio_vals[symbol], 0.5),
            "atr_ratio_p90": _quantile(atr_ratio_vals[symbol], 0.9),
            "distance_to_poc_bps_p50": _quantile(dist_poc_vals[symbol], 0.5),
            "distance_to_poc_bps_p90": _quantile(dist_poc_vals[symbol], 0.9),
        }

    # 3) Router profile audit across sampled contexts
    router = get_profile_router(config=RouterConfig(), force_new=True)
    specs = router.registry.list_specs()

    profile_stats: Dict[str, Dict[str, ProfileAuditStats]] = {
        s: {spec.id: ProfileAuditStats() for spec in specs} for s in symbols
    }
    fail_reasons: Dict[str, Counter] = defaultdict(Counter)

    for symbol in symbols:
        symbol_contexts = contexts_by_symbol.get(symbol, [])
        if not symbol_contexts:
            continue
        for market_context, features in symbol_contexts:
            context = _build_context_vector(symbol, market_context, features)
            if context is None:
                continue

            best_profile: Optional[str] = None
            best_score = -math.inf

            for spec in specs:
                st = profile_stats[symbol][spec.id]
                st.samples += 1

                score_obj = router._score_profile(spec, context)  # pylint: disable=protected-access
                if score_obj.rule_passed:
                    st.rule_pass += 1
                    st.score_sum += _safe_float(score_obj.score)
                    enabled = enabled_strategies_for_symbol(spec.strategy_ids or [], symbol)
                    if enabled:
                        st.env_eligible += 1
                        if _safe_float(score_obj.score) > best_score:
                            best_score = _safe_float(score_obj.score)
                            best_profile = spec.id
                    else:
                        st.env_blocked += 1
                else:
                    for reason in score_obj.reasons:
                        fail_reasons[symbol][_simplify_reason(reason)] += 1

            if best_profile:
                profile_stats[symbol][best_profile].top1_env_eligible += 1

    profile_audit: Dict[str, Any] = {}
    for symbol in symbols:
        rows = []
        for profile_id, st in profile_stats[symbol].items():
            row = st.to_dict()
            row["profile_id"] = profile_id
            rows.append(row)
        rows.sort(key=lambda r: (r["env_eligible_rate"], r["top1_rate"], r["avg_score_when_rule_pass"]), reverse=True)
        blocked_rows = sorted(rows, key=lambda r: (r["env_blocked_rate"], r["env_blocked"]), reverse=True)
        profile_audit[symbol] = {
            "contexts_audited": len(contexts_by_symbol.get(symbol, [])),
            "top_env_eligible_profiles": rows,
            "top_env_blocked_profiles": [r for r in blocked_rows if r["env_blocked"] > 0],
            "top_rule_fail_reasons": fail_reasons[symbol].most_common(25),
        }

    # 4) Recommendations
    recommendations: List[str] = []
    for symbol in symbols:
        sel = decision_summary["selected_profiles_by_symbol"].get(symbol, [])
        if sel:
            top = sel[0]
            if top["pct"] >= 70.0:
                recommendations.append(
                    f"{symbol}: profile concentration is high ({top['profile_id']} at {top['pct']}%). "
                    "Increase profile diversity by loosening at least one non-range profile constraint "
                    "(session/rotation/value-location) OR reduce range profile score advantage."
                )
        rejs = decision_summary["rejection_reasons_by_symbol"].get(symbol, [])
        if rejs:
            for r in rejs:
                if r["reason"] in {"no_signal", "prediction_low_confidence"} and r["pct"] >= 50.0:
                    recommendations.append(
                        f"{symbol}: {r['reason']} dominates ({r['pct']}%). Focus tuning on "
                        "entry signal thresholds/prediction calibration before loosening risk gates."
                    )
                    break
        blocked = profile_audit[symbol]["top_env_blocked_profiles"]
        if blocked and blocked[0]["env_blocked_rate"] >= 0.2:
            recommendations.append(
                f"{symbol}: env disable rules are blocking viable profiles (top blocked: {blocked[0]['profile_id']} "
                f"{blocked[0]['env_blocked_rate']*100:.1f}%). Revisit DISABLE_MEAN_REVERSION_SYMBOLS/"
                "DISABLE_STRATEGIES if this is unintended."
            )

    if not recommendations:
        recommendations.append(
            "No dominant misconfiguration detected in this sample. Next step: run this audit after at least 500 new decisions."
        )

    env_snapshot = {
        "REDIS_URL": redis_url,
        "decision_stream": decision_stream,
        "feature_stream": feature_stream,
        "DISABLE_STRATEGIES": os.getenv("DISABLE_STRATEGIES", ""),
        "DISABLE_MEAN_REVERSION_SYMBOLS": os.getenv("DISABLE_MEAN_REVERSION_SYMBOLS", ""),
        "PREDICTION_MIN_CONFIDENCE": os.getenv("PREDICTION_MIN_CONFIDENCE", ""),
        "SESSION_FILTER_ENFORCE_PREFERENCES": os.getenv("SESSION_FILTER_ENFORCE_PREFERENCES", ""),
        "SESSION_FILTER_ENFORCE_STRATEGY_SESSIONS": os.getenv("SESSION_FILTER_ENFORCE_STRATEGY_SESSIONS", ""),
        "ALLOW_NEAR_POC_ENTRIES": os.getenv("ALLOW_NEAR_POC_ENTRIES", ""),
        "TRADING_DISABLED": os.getenv("TRADING_DISABLED", ""),
    }

    result = {
        "generated_at_utc": now.isoformat(),
        "tenant_id": args.tenant_id,
        "bot_id": args.bot_id,
        "window_hours": args.hours,
        "symbols": symbols,
        "env_snapshot": env_snapshot,
        "decision_summary": decision_summary,
        "context_summary": context_summary,
        "profile_audit": profile_audit,
        "recommendations": recommendations,
    }

    timestamp_tag = now.strftime("%Y%m%d_%H%M%S")
    prefix = f"{args.output_prefix}_{timestamp_tag}"
    out_json = Path(f"{prefix}.json")
    out_md = Path(f"{prefix}.md")

    out_json.write_text(json.dumps(result, indent=2))
    out_md.write_text(
        _build_markdown_report(
            generated_at=now,
            args=args,
            env_snapshot=env_snapshot,
            decision_summary=decision_summary,
            context_summary=context_summary,
            profile_audit=profile_audit,
            recommendations=recommendations,
        )
    )

    print(f"Audit complete.")
    print(f"JSON: {out_json}")
    print(f"MD:   {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

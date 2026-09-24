"""Offline, stdlib-only paired-universe preparation. No provider, DB or NAV calls."""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import date, datetime, time
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
SYMBOL = re.compile(r"[0-9]{6}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
CARD_FIELDS = (
    "symbol", "exchange", "security_type", "industry", "industry_version", "data_date",
    "source", "raw_sha256", "published_at", "observed_at", "features_as_of", "industry_as_of",
    "adjustment_basis", "amount_unit", "close_raw", "return20", "return60", "amount20_cny",
    "volatility20", "is_st", "halted", "listing_sessions", "history_sessions",
)


class InvalidInput(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidInput(message)


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse(raw):
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: fail(f"nonfinite JSON: {value}"))


def load(path):
    return parse(Path(path).read_bytes())


def fail(message):
    raise InvalidInput(message)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def symbols(values, name):
    require(isinstance(values, list) and all(isinstance(s, str) and SYMBOL.fullmatch(s)
                                            for s in values), f"{name}: invalid symbols")
    require(len(values) == len(set(values)), f"{name}: duplicate symbols")
    return set(values)


def instant(value):
    require(isinstance(value, str), "timestamp must be a string")
    result = datetime.fromisoformat(value)
    require(result.utcoffset() is not None, "timezone required")
    return result


def number(value, name):
    require(type(value) in (int, float) and math.isfinite(value), f"{name}: invalid number")
    return value


def validate_row(row, session, cutoff, policy):
    require(isinstance(row, dict), "row must be object")
    require(row.get("data_date") == session, "stale or future market date")
    require(row.get("exchange") in ("SSE", "SZSE", "BSE")
            and row.get("security_type") == "A_SHARE", "not a covered A-share security")
    for field in ("source", "industry", "industry_version"):
        require(isinstance(row.get(field), str) and 0 < len(row[field]) <= 100,
                f"missing/oversized {field}")
    require(HASH.fullmatch(row.get("raw_sha256", "")), "missing raw receipt hash")
    observed = instant(row["observed_at"])
    published = instant(row["published_at"])
    require(published <= observed <= cutoff, "future or inconsistent source timestamp")
    close_time = datetime.combine(date.fromisoformat(session), time(15),
                                  ZoneInfo(policy["timezone"]))
    require(published >= close_time, "market row published before session close")
    require(observed.astimezone(ZoneInfo(policy["timezone"])).date().isoformat() == session,
            "source observed on wrong session")
    require(close_time <= instant(row["features_as_of"]) <= observed,
            "stale, future or unobserved features")
    require(instant(row["industry_as_of"]) <= cutoff, "future industry")
    require(row.get("adjustment_basis") == "pit_total_return", "unverified feature price basis")
    require(row.get("amount_unit") == "CNY", "wrong amount unit")
    for field in ("is_st", "halted"):
        require(type(row.get(field)) is bool, f"unknown {field}")
    for field in ("listing_sessions", "history_sessions"):
        require(type(row.get(field)) is int and row[field] >= 0, f"invalid {field}")
    require(number(row.get("close_raw"), "close_raw") > 0, "nonpositive price")
    for field in ("amount20_cny", "volatility20"):
        require(number(row.get(field), field) >= 0, f"negative {field}")
    for field in ("return20", "return60"):
        require(number(row.get(field), field) >= -1, f"invalid {field}")


def exclusion(row, policy):
    if row["is_st"]:
        return "ST"
    if row["halted"]:
        return "halted"
    if row["listing_sessions"] < policy["minimum_listing_sessions"]:
        return "young_listing"
    if row["history_sessions"] < policy["minimum_history_sessions"]:
        return "short_history"
    if row["amount20_cny"] < policy["minimum_amount20_cny"]:
        return "illiquid"
    return None


def rank_scores(rows, weights):
    """Common full-universe midrank percentiles; ties have identical scores."""
    ordered = {key: sorted(r[key] for r in rows) for key in weights}
    result = {}
    for row in rows:
        score = 0.0
        for key, weight in weights.items():
            values = ordered[key]
            percentile = ((bisect_left(values, row[key]) + bisect_right(values, row[key]) - 1)
                          / (2 * (len(values) - 1))) if len(values) > 1 else 0.5
            score += weight * percentile
        result[row["symbol"]] = round(score, 12)
    return result


def choose(rows, scores, policy):
    selected, sectors = [], Counter()
    for row in sorted(rows, key=lambda r: (-scores[r["symbol"]], r["symbol"])):
        if sectors[row["industry"]] >= policy["sector_candidate_limit"]:
            continue
        selected.append(row["symbol"])
        sectors[row["industry"]] += 1
        if len(selected) == policy["candidate_limit"]:
            break
    return selected


def prepare(snapshot, baseline, policy):
    require(policy["activation"] == {"network": False, "model": False,
                                      "economic": False, "production_write": False},
            "offline activation contract changed")
    fixed = symbols([s["symbol"] for s in baseline["stocks"]], "baseline")
    require(len(fixed) == 25, "baseline must contain exactly 25 symbols")
    session = snapshot["session"]
    day = date.fromisoformat(session)
    require(day <= date.fromisoformat(policy["expires_on"]), "protocol expired")
    cutoff = instant(snapshot["cutoff"])
    local_cutoff = cutoff.astimezone(ZoneInfo(policy["timezone"]))
    require(local_cutoff.date() == day and local_cutoff.time() >= time(15),
            "cutoff must be after same-day close")
    require(snapshot.get("kind") in ("synthetic", "external_unverified"), "unknown input kind")
    require(snapshot.get("scope") == policy["scope"], "market scope mismatch")
    require(snapshot.get("is_trading_session") is True, "not a confirmed trading session")
    require(HASH.fullmatch(snapshot.get("calendar_sha256", "")), "missing calendar provenance")
    require(snapshot.get("universe_effective_date") == session, "universe is not same-day")
    require(instant(snapshot["universe_observed_at"]) <= cutoff, "future universe")
    require(snapshot.get("universe_source"), "missing universe source")
    require(isinstance(snapshot.get("industry_version"), str)
            and bool(snapshot["industry_version"]), "missing common industry version")
    expected = symbols(snapshot["expected_symbols"], "expected")
    require(bool(expected) and fixed <= expected, "full manifest must contain fixed baseline")
    require(type(snapshot.get("provider_total")) is int
            and snapshot["provider_total"] == len(expected), "provider denominator mismatch")
    require(snapshot.get("pagination_complete") is True, "truncated universe response")
    require(snapshot.get("universe_sha256") == digest(sorted(expected)), "universe hash mismatch")
    rows = snapshot["rows"]
    require(isinstance(rows, list) and all(isinstance(r, dict) for r in rows), "bad rows")
    received = symbols([r.get("symbol") for r in rows], "rows")
    missing = symbols(snapshot["missing_symbols"], "missing")
    require(not received & missing and received | missing == expected,
            "missing/unexpected rows not reconciled with fixed denominator")
    blockers, invalid, excluded, valid = [], {}, {}, {}
    for row in rows:
        symbol = row["symbol"]
        try:
            validate_row(row, session, cutoff, policy)
            require(row["industry_version"] == snapshot["industry_version"],
                    "inconsistent industry classification")
            valid[symbol] = row
            reason = exclusion(row, policy)
            if reason:
                excluded[symbol] = reason
        except (InvalidInput, ValueError, KeyError, TypeError) as exc:
            invalid[symbol] = str(exc)
    coverage = len(valid) / len(expected)
    if coverage < policy["minimum_coverage"]:
        blockers.append("coverage_below_98_percent")
    if not fixed <= valid.keys():
        blockers.append("fixed_baseline_missing_or_invalid")
    require(set(snapshot["synthetic_holdings"]) == {"A", "B"}, "exactly two holdings arms required")
    holdings = {}
    for arm in ("A", "B"):
        holdings[arm] = symbols(snapshot["synthetic_holdings"][arm], f"{arm} holdings")
        require(holdings[arm] <= expected, "holding missing from market manifest")
        require(len(holdings[arm]) <= policy["holdings_limit"], "holdings limit exceeded")
        if not holdings[arm] <= valid.keys():
            blockers.append(f"{arm}_holding_data_missing_or_invalid")
    eligible = [r for s, r in sorted(valid.items()) if s not in excluded]
    scores = rank_scores(eligible, policy["score_weights"])
    selections = {
        "A": choose([r for r in eligible if r["symbol"] in fixed], scores, policy),
        "B": choose(eligible, scores, policy),
    }
    # Budget comparisons keep the whole prompt, not just the rows, within bounds.
    payloads = {}
    for arm in ("A", "B"):
        cards = []
        for symbol in sorted(set(selections[arm]) | holdings[arm]):
            if symbol in valid:
                cards.append({**{key: valid[symbol][key] for key in CARD_FIELDS},
                              "screen_score": scores.get(symbol),
                              "holding": symbol in holdings[arm],
                              "entry_candidate": symbol in selections[arm],
                              "exclusion": excluded.get(symbol)})
        payload = {
            "schema": "universe_comparison.screen_only.v1", "session": session,
            "cutoff": snapshot["cutoff"], "arm": arm,
            "instruction": "仅作候选质量诊断。不得输出订单或净值。无财报/公告证据时明确缺口；不得把缺失当利好。",
            "cards": cards,
            "research_evidence": "financials/news/counterevidence not attached; provider acceptance pending",
        }
        size = len(encoded(payload))
        if size > policy["payload_bytes_per_arm"]:
            blockers.append(f"{arm}_payload_budget_exceeded")
        payloads[arm] = {"candidate_symbols": selections[arm],
                         "candidate_count": len(selections[arm]),
                         "holding_symbols": sorted(holdings[arm]),
                         "payload_bytes": size, "payload_sha256": digest(payload), "payload": payload}
    a, b = set(selections["A"]), set(selections["B"])
    return {
        "schema": "universe_comparison.preflight.v1",
        "status": "blocked" if blockers else "offline_prepared",
        "input_kind": snapshot["kind"], "session": session, "blockers": blockers,
        "expected": len(expected), "received": len(rows), "valid": len(valid),
        "coverage": coverage, "missing_symbols": sorted(missing), "invalid": invalid,
        "excluded": excluded, "eligible": len(eligible), "arms": payloads,
        "overlap": len(a & b), "new_to_fixed_pool": sorted(b - fixed),
        "initial_call_order": ["A", "B"] if day.toordinal() % 2 == 0 else ["B", "A"],
        "policy_sha256": digest(policy), "baseline_sha256": digest(baseline),
        "input_sha256": digest(snapshot), "runtime_model_calls": 0,
        "runtime_provider_calls": 0, "token_usage": None, "billed_cost": None,
        "economic_activation": False, "outbound_ready": False,
        "limitations": ["source hashes and calendar flags are declarations, not independent attestation",
                        "synthetic fixtures do not establish real full-market coverage",
                        "no financial/news pack, model invocation, account ledger or NAV in this tool",
                        "equal candidate caps do not guarantee equal candidate counts or token usage"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        # Bind these exact checked-in candidate files; no arbitrary policy override.
        registration = load(ROOT / "registration.json")
        require(set(registration["files"]) == {"prepare.py", "protocol.json", "baseline-universe.json"},
                "registration must bind exact runner, policy and baseline")
        for name, wanted in registration["files"].items():
            require(Path(name).name == name, "invalid registration filename")
            require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == wanted,
                    f"registration hash mismatch: {name}")
        raw_input = args.input.read_bytes()
        result = prepare(parse(raw_input), load(ROOT / "baseline-universe.json"),
                         load(ROOT / "protocol.json"))
        result["input_file_sha256"] = hashlib.sha256(raw_input).hexdigest()
        # Exclusive output leaves previous evidence untouched, even across concurrent runs.
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({k: result[k] for k in ("status", "expected", "coverage", "blockers")},
                         ensure_ascii=False))
        return 2 if result["blockers"] else 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"preflight refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

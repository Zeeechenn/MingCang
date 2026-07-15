"""M68 observe-only production mirror for the event-pyramid news layer.

The module reads production-shaped evidence, prices, and the latest official
signal, then writes only ``news_shadow_*`` tables. It never imports or calls
the official signal persistence path and never mutates signals or positions.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import math
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from datetime import time as dt_time
from typing import Any, cast

from sqlalchemy import case
from sqlalchemy.orm import Session

from backend.config import active_signal_weights, settings
from backend.data.models.market import Price, Stock
from backend.data.models.news_shadow import NewsShadowFeedback, NewsShadowRun
from backend.data.models.signals import Signal
from backend.data.news_clustering import cluster_evidence
from backend.data.news_evidence import NewsEvidence
from backend.data.news_extraction import prescreen_cluster
from backend.data.news_layer_v2 import evidence_from_db, score_news_v2
from backend.data.news_trigger import PreviousTriggerState
from backend.data.orm import _utcnow
from backend.decision.signal_policy import score_to_recommendation
from backend.ops.llm_budget import get_today_spend

logger = logging.getLogger(__name__)

PROFILE_PRODUCTION_MIRROR = "production_mirror"
CACHE_VERSION = "m68.news-shadow.v1"
STATUS_EVIDENCE = "evidence"
STATUS_NO_EVIDENCE = "no_evidence"
STATUS_VERIFIED_NO_NEWS = "verified_no_news"
STATUS_FETCH_FAILED = "fetch_failed"
STATUS_SCORE_FAILED = "score_failed"

_VALID_COLLECTION_OUTCOMES = {"success", "failed", "not_run"}


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _as_of_parts(value: str | date | datetime) -> tuple[str, datetime]:
    if isinstance(value, datetime):
        day = value.date().isoformat()
        return day, value.replace(tzinfo=None)
    parsed = value if isinstance(value, date) else date.fromisoformat(value)
    return parsed.isoformat(), datetime.combine(parsed, dt_time(23, 59, 59))


def _active_cn_symbols(db: Session) -> list[str]:
    rows = (
        db.query(Stock.symbol)
        .filter(Stock.active.is_(True), Stock.market == "CN")
        .order_by(Stock.symbol.asc())
        .all()
    )
    return [str(row[0]) for row in rows]


def _latest_official_signal(db: Session, symbol: str, as_of: str) -> Signal | None:
    return (
        db.query(Signal)
        .filter(Signal.symbol == symbol, Signal.date <= as_of)
        .order_by(Signal.date.desc(), Signal.id.desc())
        .first()
    )


def _price_volume_inputs(
    db: Session,
    symbol: str,
    as_of: str,
) -> tuple[float | None, float | None, dict[str, Any]]:
    rows = (
        db.query(Price)
        .filter(Price.symbol == symbol, Price.date <= as_of)
        .order_by(Price.date.desc(), Price.id.desc())
        .limit(21)
        .all()
    )
    price_change_pct: float | None = None
    if len(rows) >= 2 and rows[1].close not in (None, 0):
        price_change_pct = (float(rows[0].close) / float(rows[1].close) - 1.0) * 100.0

    volume_ratio: float | None = None
    prior_volumes = [float(row.volume) for row in rows[1:21] if row.volume is not None]
    # The production trigger contract calls for a trailing 20-session baseline;
    # a shorter denominator is exposed as missing instead of silently changing it.
    if len(prior_volumes) == 20 and rows[0].volume is not None:
        mean_volume = sum(prior_volumes) / len(prior_volumes)
        if mean_volume > 0:
            volume_ratio = float(rows[0].volume) / mean_volume

    audit = {
        "latest_price_date": rows[0].date if rows else None,
        "price_bars_available": len(rows),
        "volume_baseline_sessions": len(prior_volumes),
        "price_change_available": price_change_pct is not None,
        "volume_ratio_available": volume_ratio is not None,
    }
    return price_change_pct, volume_ratio, audit


def _previous_trigger_state(
    db: Session,
    symbol: str,
    as_of: str,
    profile: str,
) -> PreviousTriggerState | None:
    row = (
        db.query(NewsShadowRun)
        .filter(
            NewsShadowRun.symbol == symbol,
            NewsShadowRun.as_of < as_of,
            NewsShadowRun.profile == profile,
        )
        .order_by(NewsShadowRun.as_of.desc(), NewsShadowRun.id.desc())
        .first()
    )
    if row is None:
        return None
    evidence = _json_loads(row.evidence_json, {})
    return PreviousTriggerState(
        as_of=datetime.combine(date.fromisoformat(row.as_of), dt_time(23, 59, 59)),
        triggered=bool(_json_loads(row.attribution_json, None)),
        max_source_diversity=int(evidence.get("max_source_diversity") or 0),
    )


def _evidence_audit(
    evidence: Sequence[NewsEvidence],
    *,
    collection_outcome: str,
    price_volume_audit: Mapping[str, Any],
) -> dict[str, Any]:
    content_counts = Counter(item.content_status for item in evidence)
    clusters = cluster_evidence(list(evidence)) if evidence else []
    cluster_audits = [
        {
            "cluster_id": cluster.cluster_id,
            "event_type": cluster.event_type,
            "source_diversity": cluster.source_diversity,
            **prescreen_cluster(cluster),
        }
        for cluster in clusters
    ]
    manifests = [
        {
            "evidence_id": hashlib.sha256(
                f"{item.symbol}|{item.url}|{item.published_at.isoformat()}|{item.title}".encode()
            ).hexdigest()[:20],
            "title": item.title,
            "url": item.url,
            "published_at": item.published_at.isoformat(),
            "source": item.source_name,
            "provider": item.provider,
            "content_status": item.content_status,
        }
        for item in evidence
    ]
    return {
        "collection_outcome": collection_outcome,
        "count": len(evidence),
        "providers": sorted({item.provider for item in evidence if item.provider}),
        "sources": sorted({item.source_name for item in evidence if item.source_name}),
        "source_diversity": len({item.source_name for item in evidence if item.source_name}),
        "max_source_diversity": max((cluster.source_diversity for cluster in clusters), default=0),
        "max_l0_materiality": max(
            (float(item["materiality"]) for item in cluster_audits),
            default=None,
        ),
        "high_materiality_cluster_count": sum(
            float(item["materiality"]) >= 0.70 for item in cluster_audits
        ),
        "cluster_audits": cluster_audits,
        "content_status_counts": dict(sorted(content_counts.items())),
        "content_coverage": (
            round(sum(item.content_status != "title_only" for item in evidence) / len(evidence), 4)
            if evidence
            else None
        ),
        "url_coverage": (
            round(sum(bool(item.url) for item in evidence) / len(evidence), 4)
            if evidence
            else None
        ),
        "earliest_published_at": min((item.published_at for item in evidence), default=None),
        "latest_published_at": max((item.published_at for item in evidence), default=None),
        "price_volume": dict(price_volume_audit),
        "items": manifests,
    }


def _counterfactual(
    official: Signal | None,
    *,
    pyramid_composite: float,
    as_of: str,
) -> dict[str, Any]:
    if official is None:
        return {
            "composite": None,
            "recommendation": None,
            "score_delta": None,
            "would_change_action": False,
            "note": "no official signal was available as-of",
        }
    weights = active_signal_weights(date.fromisoformat(as_of))
    if official.date != as_of:
        return {
            "composite": None,
            "recommendation": None,
            "score_delta": None,
            "would_change_action": False,
            "note": f"official signal is stale ({official.date}); same-day comparison required",
        }
    missing_legs: list[str] = []
    if weights.quant > 0 and official.quant_score is None:
        missing_legs.append("quant")
    if weights.technical > 0 and official.technical_score is None:
        missing_legs.append("technical")
    if missing_legs:
        return {
            "composite": None,
            "recommendation": None,
            "score_delta": None,
            "would_change_action": False,
            "note": f"official weighted legs missing: {','.join(missing_legs)}",
        }
    quant = float(official.quant_score or 0.0)
    technical = float(official.technical_score or 0.0)
    composite = (
        quant * weights.quant
        + technical * weights.technical
        + float(pyramid_composite) * 100.0 * weights.sentiment
    )
    composite = round(max(-100.0, min(100.0, composite)), 1)
    recommendation = score_to_recommendation(composite, date.fromisoformat(as_of))
    return {
        "composite": composite,
        "recommendation": recommendation,
        "score_delta": round(composite - float(official.composite_score), 1),
        "would_change_action": recommendation != official.recommendation,
        "note": (
            "mechanical same-day sentiment-leg swap only; excludes debate, research "
            "constraints, stops, sizing, and execution"
        ),
    }


def _status_without_evidence(collection_outcome: str) -> str:
    if collection_outcome == "success":
        return STATUS_VERIFIED_NO_NEWS
    if collection_outcome == "failed":
        return STATUS_FETCH_FAILED
    return STATUS_NO_EVIDENCE


def _event_risk_slot(
    signal: Any,
    evidence_audit: Mapping[str, Any],
) -> tuple[str, list[str]]:
    """Map a triggered event to review priority, never to bullish/bearish direction."""
    attribution = signal.attribution_card
    if attribution is None:
        max_materiality = evidence_audit.get("max_l0_materiality")
        if max_materiality is not None and float(max_materiality) >= 0.70:
            return "high", ["high_importance_untriggered", f"l0_materiality:{float(max_materiality):.2f}"]
        return "low", ["l1_not_triggered"]
    reasons = list(signal.trigger_reasons)
    main_cause = str(getattr(attribution, "main_cause", "market_sentiment"))
    reasons.append(f"main_cause:{main_cause}")
    thesis_recheck = bool(getattr(attribution, "thesis_recheck", False))
    if thesis_recheck and float(signal.confidence) >= 0.5:
        return "high", reasons
    return "medium", reasons


def _apply_common_run_fields(
    row: NewsShadowRun,
    *,
    official: Signal | None,
    evidence_audit: Mapping[str, Any],
    price_change_pct: float | None,
    volume_ratio: float | None,
    tier: str,
) -> None:
    row.legacy_signal_id = official.id if official else None
    row.legacy_signal_date = official.date if official else None
    row.legacy_sentiment_score = official.sentiment_score if official else None
    row.legacy_composite_score = official.composite_score if official else None
    row.legacy_recommendation = official.recommendation if official else None
    row.legacy_summary = "latest official signal at or before the mirror date" if official else "no official signal available"
    row.price_change_pct = price_change_pct
    row.volume_ratio = volume_ratio
    row.evidence_json = _json_dumps(evidence_audit)
    row.model_tier = tier
    row.provider = settings.ai_provider
    row.cache_version = CACHE_VERSION
    row.updated_at = _utcnow()


def _clear_score_fields(row: NewsShadowRun) -> None:
    row.pyramid_sentiment_score = None
    row.pyramid_composite = None
    row.news_score = None
    row.flow_score = None
    row.confidence = None
    row.counterfactual_composite = None
    row.counterfactual_recommendation = None
    row.counterfactual_note = None
    row.score_delta = None
    row.would_change_action = False
    row.event_risk_level = "unavailable"
    row.event_risk_reasons_json = "[]"
    row.trigger_reasons_json = "[]"
    row.attribution_json = None
    row.degradation_flags_json = "[]"
    row.latency_ms = None
    row.tokens_spent = None


def run_production_mirror(
    *,
    as_of: str | date | datetime,
    db: Session,
    symbols: Sequence[str] | None = None,
    limit: int | None = None,
    profile: str = PROFILE_PRODUCTION_MIRROR,
    tier: str = "capable",
    lookback_days: int = 3,
    include_announcements: bool = True,
    collection_outcomes: Mapping[str, str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run the pyramid against production-shaped DB evidence and persist shadow rows.

    ``collection_outcomes`` is deliberately explicit. ``success`` plus no
    evidence means verified-no-news, ``failed`` means fetch-failed, while the
    default ``not_run`` only means the production store had no evidence.
    """
    day, as_of_dt = _as_of_parts(as_of)
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")
    selected_source = _active_cn_symbols(db) if symbols is None else symbols
    selected = list(dict.fromkeys(selected_source))
    if limit is not None:
        selected = selected[:limit]
    outcomes = dict(collection_outcomes or {})
    invalid = {value for value in outcomes.values() if value not in _VALID_COLLECTION_OUTCOMES}
    if invalid:
        raise ValueError(f"invalid collection outcomes: {sorted(invalid)}")

    counts: Counter[str] = Counter()
    tokens_total = 0
    tokens_unknown = False
    started = time.perf_counter()

    for symbol in selected:
        existing = (
            db.query(NewsShadowRun)
            .filter(
                NewsShadowRun.symbol == symbol,
                NewsShadowRun.as_of == day,
                NewsShadowRun.profile == profile,
            )
            .one_or_none()
        )
        if existing is not None and not force:
            counts["cache_hit"] += 1
            counts[existing.status] += 1
            continue

        row = existing or NewsShadowRun(
            run_id=f"m68:{profile}:{day}:{symbol}",
            symbol=symbol,
            as_of=day,
            profile=profile,
            status=STATUS_NO_EVIDENCE,
        )
        if existing is None:
            db.add(row)

        collection_outcome = outcomes.get(symbol, "not_run")
        official: Signal | None = None
        price_change_pct: float | None = None
        volume_ratio: float | None = None
        pv_audit: dict[str, Any] = {}
        evidence_audit: dict[str, Any] = {
            "collection_outcome": collection_outcome,
            "count": None,
            "price_volume": pv_audit,
        }
        try:
            official = _latest_official_signal(db, symbol, day)
            price_change_pct, volume_ratio, pv_audit = _price_volume_inputs(db, symbol, day)
            evidence = evidence_from_db(
                symbol,
                as_of_dt,
                lookback_days,
                db,
                include_announcements=include_announcements,
            )
            evidence_audit = _evidence_audit(
                evidence,
                collection_outcome=collection_outcome,
                price_volume_audit=pv_audit,
            )
            _apply_common_run_fields(
                row,
                official=official,
                evidence_audit=evidence_audit,
                price_change_pct=price_change_pct,
                volume_ratio=volume_ratio,
                tier=tier,
            )

            if not evidence:
                row.status = _status_without_evidence(collection_outcome)
                _clear_score_fields(row)
                row.counterfactual_note = "no evidence was scored"
                row.latency_ms = 0
                row.tokens_spent = 0
                row.error = None
                db.commit()
                counts[row.status] += 1
                continue

            before_tokens, before_unknown = get_today_spend("sentiment", db=db)
            score_started = time.perf_counter()
            signal = score_news_v2(
                evidence,
                as_of_dt,
                tier=tier,
                previous_state=_previous_trigger_state(db, symbol, day, profile),
                price_change_pct=price_change_pct,
                volume_ratio=volume_ratio,
                cache_namespace=f"m68:{profile}",
            )
            latency_ms = round((time.perf_counter() - score_started) * 1000)
            after_tokens, after_unknown = get_today_spend("sentiment", db=db)
            token_delta = None if before_unknown or after_unknown else max(0, after_tokens - before_tokens)
            if token_delta is None:
                tokens_unknown = True
            else:
                tokens_total += token_delta

            counterfactual = _counterfactual(
                official,
                pyramid_composite=signal.composite,
                as_of=day,
            )
            row.status = STATUS_EVIDENCE
            row.pyramid_sentiment_score = round(float(signal.composite) * 100.0, 4)
            row.pyramid_composite = float(signal.composite)
            row.news_score = signal.news_score
            row.flow_score = signal.flow_score
            row.confidence = signal.confidence
            row.counterfactual_composite = counterfactual["composite"]
            row.counterfactual_recommendation = counterfactual["recommendation"]
            row.counterfactual_note = counterfactual["note"]
            row.score_delta = counterfactual["score_delta"]
            row.would_change_action = bool(counterfactual["would_change_action"])
            event_risk_level, event_risk_reasons = _event_risk_slot(signal, evidence_audit)
            row.event_risk_level = event_risk_level
            row.event_risk_reasons_json = _json_dumps(event_risk_reasons)
            row.trigger_reasons_json = _json_dumps(signal.trigger_reasons)
            row.attribution_json = (
                _json_dumps(dataclasses.asdict(cast(Any, signal.attribution_card)))
                if signal.attribution_card is not None and dataclasses.is_dataclass(signal.attribution_card)
                else None
            )
            row.degradation_flags_json = _json_dumps(signal.degradation_flags)
            row.latency_ms = latency_ms
            row.tokens_spent = token_delta
            row.error = None
            db.commit()
            counts[row.status] += 1
            if row.would_change_action:
                counts["would_change_action"] += 1
            if signal.attribution_card is not None:
                counts["triggered"] += 1
        except Exception as exc:  # noqa: BLE001 - one symbol must not abort the mirror.
            logger.warning("M68 news shadow failed for %s: %s", symbol, exc)
            db.rollback()
            evidence_audit["price_volume"] = pv_audit
            failed = (
                db.query(NewsShadowRun)
                .filter(
                    NewsShadowRun.symbol == symbol,
                    NewsShadowRun.as_of == day,
                    NewsShadowRun.profile == profile,
                )
                .one_or_none()
            ) or NewsShadowRun(
                run_id=f"m68:{profile}:{day}:{symbol}",
                symbol=symbol,
                as_of=day,
                profile=profile,
                status=STATUS_SCORE_FAILED,
            )
            if failed.id is None:
                db.add(failed)
            _apply_common_run_fields(
                failed,
                official=official,
                evidence_audit=evidence_audit,
                price_change_pct=price_change_pct,
                volume_ratio=volume_ratio,
                tier=tier,
            )
            _clear_score_fields(failed)
            failed.status = STATUS_SCORE_FAILED
            failed.error = f"{type(exc).__name__}: {exc}"
            failed.counterfactual_note = "scoring failed; no comparison is valid"
            failed.tokens_spent = None
            db.commit()
            counts[STATUS_SCORE_FAILED] += 1

    persisted = (
        db.query(NewsShadowRun)
        .filter(NewsShadowRun.as_of == day, NewsShadowRun.profile == profile)
        .all()
    )
    event_risk_counts = Counter(row.event_risk_level for row in persisted)
    priority = {"high": 0, "medium": 1, "low": 2, "unavailable": 3}
    attention_rows = sorted(
        persisted,
        key=lambda row: (
            priority.get(row.event_risk_level, 4),
            not bool(row.would_change_action),
            -(abs(float(row.score_delta)) if row.score_delta is not None else 0.0),
            row.symbol,
        ),
    )[:10]
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    return {
        "ok": counts[STATUS_SCORE_FAILED] == 0,
        "schema_version": CACHE_VERSION,
        "as_of": day,
        "profile": profile,
        "n_symbols": len(selected),
        "counts": dict(sorted(counts.items())),
        "event_risk_counts": dict(sorted(event_risk_counts.items())),
        "attention": [
            {
                "symbol": row.symbol,
                "level": row.event_risk_level,
                "reasons": _json_loads(row.event_risk_reasons_json, []),
                "would_change_action": row.would_change_action,
                "score_delta": row.score_delta,
                "confidence": row.confidence,
                "main_cause": (
                    _json_loads(row.attribution_json, {}) or {}
                ).get("main_cause"),
                "thesis_recheck": bool(
                    (_json_loads(row.attribution_json, {}) or {}).get("thesis_recheck")
                ),
                "degradation_flags": _json_loads(row.degradation_flags_json, []),
            }
            for row in attention_rows
            if row.event_risk_level in {"high", "medium"}
        ],
        "tokens_spent": None if tokens_unknown else tokens_total,
        "tokens_spent_unknown": tokens_unknown,
        "elapsed_ms": elapsed_ms,
        "write_boundary": "news_shadow_runs only; official signals and positions untouched",
    }


def _run_to_dict(row: NewsShadowRun, *, include_evidence: bool = False) -> dict[str, Any]:
    payload = {
        "run_id": row.run_id,
        "symbol": row.symbol,
        "as_of": row.as_of,
        "profile": row.profile,
        "status": row.status,
        "legacy": {
            "signal_id": row.legacy_signal_id,
            "signal_date": row.legacy_signal_date,
            "sentiment_score": row.legacy_sentiment_score,
            "composite_score": row.legacy_composite_score,
            "recommendation": row.legacy_recommendation,
            "summary": row.legacy_summary,
        },
        "pyramid": {
            "sentiment_score": row.pyramid_sentiment_score,
            "composite": row.pyramid_composite,
            "news_score": row.news_score,
            "flow_score": row.flow_score,
            "confidence": row.confidence,
            "trigger_reasons": _json_loads(row.trigger_reasons_json, []),
            "attribution": _json_loads(row.attribution_json, None),
            "degradation_flags": _json_loads(row.degradation_flags_json, []),
        },
        "counterfactual": {
            "composite_score": row.counterfactual_composite,
            "recommendation": row.counterfactual_recommendation,
            "note": row.counterfactual_note,
            "score_delta": row.score_delta,
            "would_change_action": row.would_change_action,
        },
        "event_risk": {
            "level": row.event_risk_level,
            "reasons": _json_loads(row.event_risk_reasons_json, []),
            "meaning": "review priority for event/volatility risk; not a direction forecast",
        },
        "price_volume": {
            "price_change_pct": row.price_change_pct,
            "volume_ratio": row.volume_ratio,
        },
        "model_tier": row.model_tier,
        "provider": row.provider,
        "cache_version": row.cache_version,
        "latency_ms": row.latency_ms,
        "tokens_spent": row.tokens_spent,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    evidence = _json_loads(row.evidence_json, {})
    payload["evidence"] = evidence if include_evidence else {
        key: value for key, value in evidence.items() if key != "items"
    }
    return payload


def _is_high_importance_untriggered(row: NewsShadowRun) -> bool:
    evidence = _json_loads(row.evidence_json, {})
    materiality = evidence.get("max_l0_materiality")
    return (
        materiality is not None
        and float(materiality) >= 0.70
        and not bool(_json_loads(row.attribution_json, None))
    )


def _stable_control_ids(rows: Sequence[NewsShadowRun], *, limit: int = 5) -> set[str]:
    """Choose a restart-stable control sample without relying on insertion order."""
    by_date: dict[str, list[NewsShadowRun]] = {}
    for row in rows:
        if (
            row.status == STATUS_EVIDENCE
            and not row.would_change_action
            and not _is_high_importance_untriggered(row)
        ):
            by_date.setdefault(row.as_of, []).append(row)
    selected: set[str] = set()
    for candidates in by_date.values():
        ranked = sorted(
            candidates,
            key=lambda row: hashlib.sha256(row.run_id.encode()).hexdigest(),
        )
        selected.update(row.run_id for row in ranked[:limit])
    return selected


def _review_bucket(row: NewsShadowRun, stable_control_ids: set[str]) -> str:
    if _is_high_importance_untriggered(row):
        return "high_importance_untriggered"
    if row.would_change_action:
        return "action_divergence"
    if row.run_id in stable_control_ids:
        return "stable_control"
    return "routine"


def list_shadow_runs(
    db: Session,
    *,
    as_of: str | None = None,
    symbol: str | None = None,
    only_divergent: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    query = db.query(NewsShadowRun)
    if as_of:
        query = query.filter(NewsShadowRun.as_of == as_of)
    if symbol:
        query = query.filter(NewsShadowRun.symbol == symbol)
    if only_divergent:
        query = query.filter(NewsShadowRun.would_change_action.is_(True))
    risk_priority = case(
        (NewsShadowRun.event_risk_level == "high", 0),
        (NewsShadowRun.event_risk_level == "medium", 1),
        (NewsShadowRun.event_risk_level == "low", 2),
        else_=3,
    )
    rows = (
        query.order_by(
            NewsShadowRun.as_of.desc(),
            NewsShadowRun.would_change_action.desc(),
            risk_priority.asc(),
            NewsShadowRun.id.desc(),
        )
        .limit(limit)
        .all()
    )
    control_query = db.query(NewsShadowRun)
    if as_of:
        control_query = control_query.filter(NewsShadowRun.as_of == as_of)
    stable_control_ids = _stable_control_ids(control_query.all())
    payloads = []
    for row in rows:
        payload = _run_to_dict(row)
        payload["review_bucket"] = _review_bucket(row, stable_control_ids)
        payloads.append(payload)
    review_priority = {
        "action_divergence": 0,
        "high_importance_untriggered": 1,
        "stable_control": 2,
        "routine": 3,
    }
    return sorted(
        payloads,
        key=lambda item: (
            item["as_of"],
            -review_priority.get(item["review_bucket"], 4),
        ),
        reverse=True,
    )


def get_shadow_run(db: Session, run_id: str) -> dict[str, Any] | None:
    row = db.query(NewsShadowRun).filter(NewsShadowRun.run_id == run_id).one_or_none()
    if row is None:
        return None
    payload = _run_to_dict(row, include_evidence=True)
    feedback = (
        db.query(NewsShadowFeedback)
        .filter(NewsShadowFeedback.run_id == run_id)
        .order_by(NewsShadowFeedback.id.desc())
        .all()
    )
    payload["feedback"] = [
        {
            "id": item.id,
            "category": item.category,
            "preferred_path": item.preferred_path,
            "evidence_ref": item.evidence_ref,
            "note": item.note,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in feedback
    ]
    return payload


def create_shadow_feedback(
    db: Session,
    *,
    run_id: str,
    category: str,
    preferred_path: str | None = None,
    evidence_ref: str | None = None,
    note: str | None = None,
) -> dict[str, Any] | None:
    if db.query(NewsShadowRun.id).filter(NewsShadowRun.run_id == run_id).first() is None:
        return None
    feedback = NewsShadowFeedback(
        run_id=run_id,
        category=category,
        preferred_path=preferred_path,
        evidence_ref=evidence_ref,
        note=note,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return {
        "id": feedback.id,
        "run_id": feedback.run_id,
        "category": feedback.category,
        "preferred_path": feedback.preferred_path,
        "evidence_ref": feedback.evidence_ref,
        "note": feedback.note,
        "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
    }


def shadow_summary(db: Session, *, as_of: str | None = None) -> dict[str, Any]:
    query = db.query(NewsShadowRun)
    if as_of:
        query = query.filter(NewsShadowRun.as_of == as_of)
    rows = query.all()
    stable_control_ids = _stable_control_ids(rows)
    statuses = Counter(row.status for row in rows)
    scored = [row for row in rows if row.status == STATUS_EVIDENCE]
    deltas = [abs(float(row.score_delta)) for row in scored if row.score_delta is not None and math.isfinite(row.score_delta)]
    return {
        "as_of": as_of,
        "total": len(rows),
        "statuses": dict(sorted(statuses.items())),
        "with_evidence": len(scored),
        "would_change_action": sum(bool(row.would_change_action) for row in rows),
        "triggered": sum(bool(_json_loads(row.attribution_json, None)) for row in scored),
        "price_volume_complete": sum(
            row.price_change_pct is not None and row.volume_ratio is not None for row in rows
        ),
        "event_risk": dict(sorted(Counter(row.event_risk_level for row in rows).items())),
        "mean_absolute_score_delta": round(sum(deltas) / len(deltas), 2) if deltas else None,
        "tokens_spent_known": sum(int(row.tokens_spent or 0) for row in rows if row.tokens_spent is not None),
        "tokens_unknown_runs": sum(row.tokens_spent is None and row.status == STATUS_EVIDENCE for row in rows),
        "review_queue": {
            "action_divergence": [row.run_id for row in rows if row.would_change_action],
            "high_importance_untriggered": [
                row.run_id for row in rows if _is_high_importance_untriggered(row)
            ],
            "stable_control": sorted(stable_control_ids),
        },
        "judgment": (
            "事件/风险解释优先；方向替换仍为只读反事实，不能据此改变生产动作"
        ),
    }

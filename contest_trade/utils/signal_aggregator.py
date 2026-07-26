"""Deterministic validation, deduplication, and ranking for research signals."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple


_A_SHARE_CODE = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")
_VALID_ACTIONS = {"buy", "sell", "hold"}
_YES_VALUES = {"yes", "true", "1"}


@dataclass(frozen=True)
class SignalAggregatorConfig:
    top_n: int = 10
    min_score: float = 0.55
    min_action_consensus: float = 0.60
    min_evidence_count: int = 1

    @classmethod
    def from_dict(cls, value: Optional[Dict[str, Any]]) -> "SignalAggregatorConfig":
        value = value or {}
        return cls(
            top_n=max(1, int(value.get("top_n", cls.top_n))),
            min_score=min(1.0, max(0.0, float(value.get("min_score", cls.min_score)))),
            min_action_consensus=min(
                1.0,
                max(0.0, float(value.get("min_action_consensus", cls.min_action_consensus))),
            ),
            min_evidence_count=max(
                1, int(value.get("min_evidence_count", cls.min_evidence_count))
            ),
        )


def _parse_probability(value: Any) -> Optional[float]:
    if isinstance(value, str):
        value = value.strip().replace("%", "")
    try:
        probability = float(value)
    except (TypeError, ValueError):
        return None
    if probability > 1:
        probability /= 100
    if not 0 <= probability <= 1:
        return None
    return probability


def _parse_date(value: Any) -> Optional[datetime]:
    if not value or str(value).strip().upper() == "N/A":
        return None
    text = str(value).strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None


def _clean_evidence(
    evidence_list: Iterable[Any], trigger_date: Optional[datetime]
) -> List[Dict[str, str]]:
    cleaned = []
    seen = set()
    for evidence in evidence_list or []:
        if not isinstance(evidence, dict):
            continue
        description = str(evidence.get("description", "")).strip()
        source = str(evidence.get("from_source", "")).strip()
        evidence_time = str(evidence.get("time", "N/A")).strip() or "N/A"
        parsed_time = _parse_date(evidence_time)
        if not description or not source:
            continue
        if trigger_date and parsed_time and parsed_time > trigger_date:
            continue
        key = (" ".join(description.split()).lower(), source.lower(), evidence_time)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(
            {
                "description": description,
                "time": evidence_time,
                "from_source": source,
            }
        )
    return cleaned


def _clean_limitations(limitations: Iterable[Any]) -> List[str]:
    cleaned = []
    seen = set()
    for limitation in limitations or []:
        text = str(limitation).strip()
        key = " ".join(text.split()).lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


def _validate_signal(
    signal: Any, trigger_date: Optional[datetime], min_evidence_count: int
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not isinstance(signal, dict):
        return None, "signal_not_object"
    if str(signal.get("has_opportunity", "no")).strip().lower() not in _YES_VALUES:
        return None, "no_opportunity"

    action = str(signal.get("action", "")).strip().lower()
    if action not in _VALID_ACTIONS:
        return None, "invalid_action"

    symbol_code = str(signal.get("symbol_code", "")).strip().upper()
    symbol_name = str(signal.get("symbol_name", "")).strip()
    if not _A_SHARE_CODE.fullmatch(symbol_code):
        return None, "invalid_symbol_code"
    if not symbol_name:
        return None, "missing_symbol_name"

    probability = _parse_probability(signal.get("probability"))
    if probability is None:
        return None, "invalid_probability"

    evidence = _clean_evidence(signal.get("evidence_list", []), trigger_date)
    if len(evidence) < min_evidence_count:
        return None, "insufficient_evidence"

    agent_name = str(signal.get("agent_name", "")).strip()
    if not agent_name:
        agent_id = signal.get("agent_id")
        agent_name = f"agent_{agent_id}" if agent_id is not None else "unknown"

    return {
        **signal,
        "action": action,
        "symbol_code": symbol_code,
        "symbol_name": symbol_name,
        "probability_normalized": probability,
        "evidence_list": evidence,
        "limitations": _clean_limitations(signal.get("limitations", [])),
        "agent_name": agent_name,
    }, None


def aggregate_signals(
    signals: Iterable[Any],
    trigger_time: Optional[str] = None,
    config: Optional[SignalAggregatorConfig] = None,
) -> Dict[str, Any]:
    """Validate, merge by symbol, resolve action conflicts, rank, and truncate signals."""
    config = config or SignalAggregatorConfig()
    input_signals = list(signals or [])
    trigger_date = _parse_date(trigger_time)
    valid_signals = []
    rejected = []

    for index, signal in enumerate(input_signals):
        valid, reason = _validate_signal(signal, trigger_date, config.min_evidence_count)
        if valid is None:
            rejected.append(
                {
                    "index": index,
                    "symbol_code": signal.get("symbol_code", "") if isinstance(signal, dict) else "",
                    "reason": reason,
                }
            )
        else:
            valid_signals.append(valid)

    grouped = defaultdict(list)
    for signal in valid_signals:
        grouped[signal["symbol_code"]].append(signal)

    candidates = []
    filtered = []
    for symbol_code, group in grouped.items():
        action_weights = defaultdict(float)
        for signal in group:
            action_weights[signal["action"]] += signal["probability_normalized"]
        ranked_actions = sorted(action_weights.items(), key=lambda item: (-item[1], item[0]))
        winning_action, winning_weight = ranked_actions[0]
        total_weight = sum(action_weights.values())
        action_consensus = winning_weight / total_weight if total_weight else 0.0
        if action_consensus < config.min_action_consensus:
            filtered.append({"symbol_code": symbol_code, "reason": "action_conflict"})
            continue

        winners = [signal for signal in group if signal["action"] == winning_action]
        evidence = _clean_evidence(
            [item for signal in winners for item in signal["evidence_list"]], trigger_date
        )
        limitations = _clean_limitations(
            [item for signal in group for item in signal["limitations"]]
        )
        source_agents = sorted({signal["agent_name"] for signal in winners})
        average_probability = sum(
            signal["probability_normalized"] for signal in winners
        ) / len(winners)
        evidence_quality = min(len(evidence) / 2, 1.0)
        agent_coverage = min(len(source_agents) / 2, 1.0)
        score = (
            0.50 * average_probability
            + 0.25 * action_consensus
            + 0.15 * evidence_quality
            + 0.10 * agent_coverage
        )
        if score < config.min_score:
            filtered.append({"symbol_code": symbol_code, "reason": "score_below_threshold"})
            continue

        names = Counter(signal["symbol_name"] for signal in winners)
        symbol_name = sorted(names.items(), key=lambda item: (-item[1], item[0]))[0][0]
        candidates.append(
            {
                "has_opportunity": "yes",
                "action": winning_action,
                "symbol_code": symbol_code,
                "symbol_name": symbol_name,
                "evidence_list": evidence,
                "limitations": limitations,
                "probability": round(average_probability * 100, 2),
                "aggregate_score": round(score, 4),
                "action_consensus": round(action_consensus, 4),
                "source_agents": source_agents,
                "agent_count": len(source_agents),
                "agent_id": "aggregate",
                "agent_name": "signal_aggregator",
            }
        )

    candidates.sort(key=lambda signal: (-signal["aggregate_score"], signal["symbol_code"]))
    selected = candidates[: config.top_n]
    truncated = candidates[config.top_n :]
    filtered.extend(
        {"symbol_code": signal["symbol_code"], "reason": "outside_top_n"}
        for signal in truncated
    )

    return {
        "signals": selected,
        "stats": {
            "input_count": len(input_signals),
            "valid_input_count": len(valid_signals),
            "unique_symbol_count": len(grouped),
            "output_count": len(selected),
            "rejected_count": len(rejected),
            "filtered_count": len(filtered),
            "duplicate_count": max(0, len(valid_signals) - len(grouped)),
        },
        "rejected": rejected,
        "filtered": filtered,
    }

"""统一的 JSON 信号解析器。

LLM 输出 <Output>{JSON}</Output> 的内容解析，三个调用方共用：
- research_agent._parse_json_signals
- main._try_parse_json_signals
- web/server._try_extract_json_signals

设计原则：
- 解析失败一律返回 None，调用方决定如何回退
- 字段标准化（类型安全 + 字段名映射）
- 支持 web 端格式（snake_case ↔ camelCase 转换）
"""
import json
import re
from typing import List, Dict, Optional


def _find_json_block(content: str) -> Optional[str]:
    """从 LLM 输出里抠出 JSON 字符串。返回 None 表示没找到。"""
    if not content:
        return None
    # 1. 优先 <Output>{...}</Output>
    m = re.search(r"<Output>\s*(\{.*?\})\s*</Output>", content, flags=re.DOTALL)
    if m:
        return m.group(1)
    # 2. 尝试 ```json { ... } ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.DOTALL)
    if m:
        return m.group(1)
    # 3. 宽松：仅匹配 { "signals": ... } 块（应对 split 掉标签后的情况）
    m = re.search(r"(\{[^{}]*\"signals\"[^{}]*\[.*\]\s*\})", content, flags=re.DOTALL)
    return m.group(1) if m else None


def parse_signals_from_content(content: str) -> Optional[List[Dict]]:
    """从 LLM 输出提取并解析 JSON 信号列表（snake_case 字段：symbol_code/has_opportunity）。

    返回 None 表示解析失败，调用方应回退到 XML 正则。
    返回 list 表示成功，list 为空表示 LLM 输出有效但没有信号。
    """
    json_str = _find_json_block(content)
    if not json_str:
        return None
    try:
        data = json.loads(json_str)
        signals = data.get("signals")
        if not isinstance(signals, list):
            return None
        return signals
    except (json.JSONDecodeError, ValueError):
        return None


def normalize_signal(s: Dict, thinking: str = "") -> Dict:
    """把单个信号字典标准化为内部统一格式（snake_case，evidence_list）。"""
    return {
        "has_opportunity": str(s.get("has_opportunity", "yes")).lower(),
        "action": str(s.get("action", "buy")).lower(),
        "symbol_code": str(s.get("symbol_code", "")).strip(),
        "symbol_name": str(s.get("symbol_name", "")).strip(),
        "evidence_list": [
            {
                "description": str(e.get("description", "")).strip(),
                "time": str(e.get("time", "N/A")).strip(),
                "from_source": str(e.get("from_source", "N/A")).strip(),
            }
            for e in (s.get("evidence_list") or [])
            if isinstance(e, dict)
        ],
        "limitations": [str(l).strip() for l in (s.get("limitations") or []) if str(l).strip()],
        "probability": str(s.get("probability", "")).strip(),
        "thinking": thinking,
    }


def normalize_signals(raw_signals: List[Dict], thinking: str = "") -> List[Dict]:
    """批量标准化。过滤掉非 dict 项。"""
    return [normalize_signal(s, thinking) for s in raw_signals if isinstance(s, dict)]


def parse_and_normalize(content: str) -> Optional[List[Dict]]:
    """一站式：提取 + 解析 + 标准化。返回 None 表示解析失败。"""
    raw = parse_signals_from_content(content)
    if raw is None:
        return None
    return normalize_signals(raw)


def parse_for_web(content: str) -> Optional[Dict]:
    """Web 端专用：从 markdown 抠 JSON，返回前端 renderFinalHtml 直接消费的格式。

    返回 None 表示没有 JSON；返回 dict 带 'signals'（list）和 'metrics'（dict）。
    字段名映射到前端期望：name/code/action/agent/evidence[{text,source,time}]/risks
    """
    raw_signals = parse_signals_from_content(content)
    if raw_signals is None:
        return None

    result = {"metrics": {}, "signals": [], "format": "json"}
    for s in raw_signals:
        if not isinstance(s, dict):
            continue
        evidences = [
            {
                "text": str(e.get("description", "")).strip(),
                "source": str(e.get("from_source", "")).strip(),
                "time": str(e.get("time", "")).strip(),
            }
            for e in (s.get("evidence_list") or [])
            if isinstance(e, dict)
        ]
        sig = {
            "name": str(s.get("symbol_name", "")).strip(),
            "code": str(s.get("symbol_code", "")).strip(),
            "action": str(s.get("action", "buy")).lower(),
            "agent": str(s.get("agent", "")).strip(),
            "evidence": evidences,
            "risks": [str(l).strip() for l in (s.get("limitations") or []) if str(l).strip()],
        }
        if sig["name"] or sig["code"]:
            result["signals"].append(sig)
    return result if result["signals"] else None
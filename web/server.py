#!/usr/bin/env python3
"""
ContestTrade 报告查看器 - 零依赖单文件 Web 服务

启动: uv run python web/server.py
访问: http://localhost:8765

设计理念: 机构交易终端质感。深靛蓝底 + 琥珀金强调 + 涨红跌绿。
         信号以卡片呈现，顶部信号矩阵条编码行业分布，结构即信息。
"""
import http.server
import json
import os
import re
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT.parent / "contest_trade" / "agents_workspace" / "results"
HTML_FILE = ROOT / "index.html"
PORT = 8765

HTML = HTML_FILE.read_text(encoding="utf-8") if HTML_FILE.is_file() else ""



def safe_resolve(rel_path: str):
    """安全解析相对路径，防止目录穿越。"""
    rel_path = (rel_path or "").strip().lstrip("/")
    parts = [p for p in rel_path.split("/") if p not in ("", ".", "..")]
    if not parts:
        return None
    candidate = (RESULTS_DIR / Path(*parts)).resolve()
    try:
        candidate.relative_to(RESULTS_DIR.resolve())
    except ValueError:
        return None
    return candidate


def _extract_markdown_metrics(content: str) -> dict:
    """从 markdown 元信息（执行摘要）抽取 metrics。"""
    metrics = {}
    patterns = [
        (r"\*\*分析时间\*\*[:：]\s*([^\n]+)", "time"),
        (r"\*\*数据源数量\*\*[:：]\s*(\d+)", "data_sources"),
        (r"\*\*研究信号数量\*\*[:：]\s*(\d+)", "signal_count"),
        (r"\*\*有效投资信号\*\*[:：]\s*(\d+)", "valid_count"),
        (r"\*\*信号有效率\*\*[:：]\s*([\d.]+%)", "valid_rate"),
    ]
    for pat, key in patterns:
        m = re.search(pat, content)
        if m:
            metrics[key] = m.group(1).strip()
    return metrics


def _try_extract_json_signals(content: str):
    """从 markdown 里抠出 JSON 块并解析为 web 友好格式。
    返回 None 表示没找到或解析失败（让调用方回退到 markdown 正则）。

    内部委托给 contest_trade.utils.json_signal_parser 统一实现。
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "contest_trade"))
    from utils.json_signal_parser import parse_for_web
    return parse_for_web(content)


def parse_structured(content: str) -> dict:
    """把研究报告 markdown 解析成结构化信号数据，供前端卡片渲染。

    优先级：JSON（research agent 新版输出）> markdown 正则（旧版输出）> 空结构。
    LLM 输出格式会漂移，正则解析脆弱；JSON 路径消灭漂移。
    """
    result = {"metrics": {}, "signals": [], "format": "markdown"}

    # 1. 尝试从 markdown 里抠 JSON（新 research agent 输出格式）
    json_data = _try_extract_json_signals(content)
    if json_data is not None:
        json_data["format"] = "json"
        # 从 markdown 元信息补 metrics（JSON 里通常没有这些）
        md_metrics = _extract_markdown_metrics(content)
        for k, v in md_metrics.items():
            json_data["metrics"].setdefault(k, v)
        return json_data

    # 2. 回退到 markdown 正则解析（旧报告/老格式）

    # 指标 — 宽松匹配 **key**: value 或 **key**：value（全角冒号），容错多余空格
    def _metric(patterns, text):
        for p in patterns:
            m = re.search(p, text)
            if m:
                return m.group(1).strip()
        return None

    t = _metric([r"\*\*分析时间\*\*[:：]\s*([^\n]+)", r"分析时间[:：]\s*([^\n]+)"], content)
    if t:
        result["metrics"]["time"] = t
    ds = _metric([r"\*\*数据源数量\*\*[:：]\s*(\d+)", r"数据源数量[:：]\s*(\d+)", r"数据源[:：]\s*(\d+)"], content)
    if ds:
        result["metrics"]["data_sources"] = ds
    sc = _metric([r"\*\*研究信号数量\*\*[:：]\s*(\d+)", r"研究信号数量[:：]\s*(\d+)", r"信号数量[:：]\s*(\d+)"], content)
    if sc:
        result["metrics"]["signal_count"] = sc
    vc = _metric([r"\*\*有效投资信号\*\*[:：]\s*(\d+)", r"有效投资信号[:：]\s*(\d+)", r"有效信号[:：]\s*(\d+)"], content)
    if vc:
        result["metrics"]["valid_count"] = vc
    vr = _metric([r"\*\*信号有效率\*\*[:：]\s*([\d.]+%)", r"信号有效率[:：]\s*([\d.]+%)"], content)
    if vr:
        result["metrics"]["valid_rate"] = vr

    # 按信号标题分块: 要求 #### 后跟数字编号（#### 1. 名称），避免把 ### 推荐投资信号 (9个) 误切
    signal_blocks = re.split(r"\n####\s*\d+\.\s*", content)
    for block in signal_blocks[1:]:  # 第一段是前言
        sig = {"name": "", "code": "", "action": "buy", "agent": "", "evidence": [], "risks": []}
        # 首行: 名称 (代码) — 兼容全角括号、括号缺失
        first_line = block.split("\n", 1)[0].strip()
        nm = re.match(r"(.+?)\s*[\(（]([^)）]+)[\)）]", first_line)
        if nm:
            sig["name"] = nm.group(1).strip()
            sig["code"] = nm.group(2).strip()
        else:
            sig["name"] = first_line

        # 投资动作 — 兼容 buy/买入/sell/卖出/hold/持有
        am = re.search(r"\*\*投资动作\*\*[:：]\s*(\w+)", block)
        if am:
            raw_action = am.group(1).strip().lower()
            sig["action"] = "sell" if raw_action in ("sell", "卖出") else ("hold" if raw_action in ("hold", "持有") else "buy")
        # 分析来源
        ag = re.search(r"\*\*分析来源\*\*[:：]*(.+)", block)
        if ag:
            sig["agent"] = ag.group(1).strip()

        # 证据: 每条以数字. 开头，结尾是 (来源: xxx, 时间: xxx) 或 （来源：xxx）
        ev_section = re.search(r"支撑证据[^\n:：]*[:：]?\s*\n(.*?)(?=\n-\s*\*\*风险|\*\*风险|\Z)", block, flags=re.DOTALL)
        if ev_section:
            for ev_match in re.finditer(
                r"\d+\.\s*\*\*(.+?)\*\*\s*[\(（]\s*(?:来源[:：]\s*)?(.+?)[\)）]",
                ev_section.group(1), flags=re.DOTALL
            ):
                text = ev_match.group(1).strip()
                meta = ev_match.group(2).strip()
                src, t = "", ""
                sm = re.search(r"(.+?)\s*[,，]\s*时间[:：]\s*(.+)", meta)
                if sm:
                    src = sm.group(1).strip()
                    t = sm.group(2).strip()
                else:
                    src = meta
                sig["evidence"].append({"text": text, "source": src, "time": t})

        # 风险: 风险提示后到下一个 #### / 免责声明 / 末尾
        risk_section = re.search(r"风险提示[^\n:：]*[:：]?\s*\n(.*?)(?=\n####|\n##\s|免责声明|\Z)", block, flags=re.DOTALL)
        if risk_section:
            for line in risk_section.group(1).split("\n"):
                line = re.sub(r"^\s*[-•·]\s*", "", line).strip()
                # 跳过纯分隔线/标点行
                if line and not re.fullmatch(r"[-_=*~]+", line):
                    sig["risks"].append(line)

        if sig["name"]:
            result["signals"].append(sig)

    return result


def parse_data_report(content: str) -> dict:
    """把数据报告 markdown 解析成按数据 agent 分组的结构化数据。

    剥掉开头元信息(标题/数据摘要/数据源分析详情)，每个 agent 的摘要正文 markdown 保留。
    宽松匹配：emoji 可选，但只切 h3 不切 h2 —— agent 标题用 ### 📈 XXX Agent，
    正文子标题用 ## 一、...，避免把子标题误切成 agent。
    """
    result = {"agents": []}
    # 截取"数据源分析详情"之后的内容（跳过开头元信息）— 兼容全角冒号/无冒号
    m = re.search(r"数据源分析详情\s*[:：]?\s*\n(.+?)(?=\n##\s*⚠|免责声明|\Z)", content, flags=re.DOTALL)
    body = m.group(1) if m else content
    # 只按 h3 + emoji 分块：agent 标题是 ### 📈 XXX Agent，正文子标题是 ## 一、... 或 ### 1. xxx（无 emoji）
    # 用 emoji 作为 agent 标题的锚点，避免把 ### 1. 中东局势 误切成 agent
    blocks = re.split(r"^###\s+[📈📊🔍💡]\s+", body, flags=re.MULTILINE)
    for block in blocks:
        if not block.strip():
            continue
        lines = block.split("\n", 1)
        agent_name = lines[0].strip()
        agent_body = lines[1].strip() if len(lines) > 1 else ""
        # 一次性剥掉 agent 正文开头的"标题/时间行/Documents残留/分隔横线"任意组合（只在开头 \A 匹配）
        # 兼容: # 市场信息综合摘要(可能带日期后缀) / **时间:** 或 **汇总时间:** / LongCat 检索前缀 / --- 横线
        agent_body = re.sub(
            r"\A(?:#\s*市场信息综合摘要[^\n]*\n+)?"
            r"(?:\*\*(?:汇总)?时间[：:].*?\*\*\s*\n+)?"
            r"(?:Documents:\s*Title:[^\n]*\nPublish Time:[^\n]*\nContent:\s*)?"
            r"(?:-{3,}\s*\n+)?",
            "", agent_body)
        if agent_name and agent_body:
            result["agents"].append({"name": agent_name, "body": agent_body})
    return result


class Handler(http.server.BaseHTTPRequestHandler):
    # 报告列表缓存：避免 8 秒轮询每次都 rglob 全量扫描
    _reports_cache = None  # {"mtime": float, "data": {"dates": [...]}}
    _reports_cache_time = 0.0

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._send_html(HTML)
        elif path == "/api/reports":
            self._list_reports()
        elif path == "/api/report":
            self._get_report(parsed.query)
        else:
            self._send_json(404, {"error": "not found"})

    def _list_reports(self):
        # 缓存策略：目录 mtime 没变就复用缓存，否则重建
        try:
            dir_mtime = RESULTS_DIR.stat().st_mtime if RESULTS_DIR.exists() else 0
        except OSError:
            dir_mtime = 0
        now = time.time()
        cache = self.__class__._reports_cache
        if cache and cache.get("mtime") == dir_mtime and now - self.__class__._reports_cache_time < 30:
            self._send_json(200, cache["data"])
            return

        # 按文件名时间戳把 final_report / data_report 配对成"运行组"，再按日期分组
        runs = {}  # (date, time) -> {"final": {...}, "data": {...}}
        if RESULTS_DIR.exists():
            for md in RESULTS_DIR.rglob("*.md"):
                rel = md.relative_to(RESULTS_DIR)
                st = md.stat()
                name = md.name
                ts = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})", name)
                if not ts:
                    continue
                date, tstr = ts.group(1), ts.group(2)
                kind = "final" if rel.parts and rel.parts[0] == "research_reports" else "data"
                runs.setdefault((date, tstr), {})[kind] = {
                    "type": rel.parts[0] if len(rel.parts) > 1 else "root",
                    "name": name,
                    "path": str(rel),
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                    "date": date,
                    "time": tstr,
                }
        # 按日期分组，日期内按时间倒序
        dates_map = {}
        for (date, tstr), kinds in runs.items():
            dates_map.setdefault(date, []).append({"time": tstr, **kinds})
        dates = []
        for date in sorted(dates_map.keys(), reverse=True):
            date_runs = sorted(dates_map[date], key=lambda r: r["time"], reverse=True)
            dates.append({"date": date, "runs": date_runs})
        result = {"dates": dates}
        self.__class__._reports_cache = {"mtime": dir_mtime, "data": result}
        self.__class__._reports_cache_time = now
        self._send_json(200, result)

    def _get_report(self, query):
        qs = urllib.parse.parse_qs(query)
        rel_path = qs.get("path", [""])[0]
        want_structured = qs.get("structured", ["0"])[0] == "1"
        full = safe_resolve(rel_path)
        if full is None or not full.is_file() or full.suffix != ".md":
            self._send_json(404, {"error": "报告不存在"})
            return
        try:
            content = full.read_text(encoding="utf-8")
            content = re.sub(r"\{self\.get_text\([^)]*\)\}", "免责声明", content)
            data = {"name": full.name, "content": content, "mtime": full.stat().st_mtime}

            # 优先读取同名 .json（CLI 生成的结构化报告）— 完全绕过 markdown 正则解析
            json_full = full.with_suffix(".json")
            json_data = None
            if json_full.is_file():
                try:
                    json_data = json.loads(json_full.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    json_data = None

            if want_structured and "research_reports" in rel_path:
                if json_data and json_data.get("format") == "json":
                    data["structured"] = json_data
                    data["structured_source"] = "json"
                else:
                    data["structured"] = parse_structured(content)
                    data["structured_source"] = "markdown"
            elif want_structured and "data_reports" in rel_path:
                data["structured"] = parse_data_report(content)
                data["report_type"] = "data"
                data["structured_source"] = "markdown"
            self._send_json(200, data)
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"📊 ContestTrade 信号终端")
    print(f"   访问: http://localhost:{PORT}")
    print(f"   报告目录: {RESULTS_DIR}")
    print(f"   Ctrl+C 停止")
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
ContestTrade 报告查看器 - 零依赖单文件 Web 服务

启动: uv run python web/server.py
访问: http://localhost:8765

设计理念: 机构交易终端质感。深靛蓝底 + 琥珀金强调 + 涨红跌绿。
         信号以卡片呈现，顶部信号矩阵条编码行业分布，结构即信息。
"""
import http.server
import hmac
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT.parent / "contest_trade" / "agents_workspace" / "results"
HEALTH_FILE = ROOT.parent / "contest_trade" / "agents_workspace" / "runtime" / "last_run.json"
HTML_FILE = ROOT / "index.html"
HOST = os.environ.get("CONTESTTRADE_WEB_HOST", "127.0.0.1")
PORT = int(os.environ.get("CONTESTTRADE_WEB_PORT", "8765"))
WEB_PASSWORD = os.environ.get("CONTESTTRADE_WEB_PASSWORD", "")
SESSION_TTL_SECONDS = int(os.environ.get("CONTESTTRADE_WEB_SESSION_TTL_SECONDS", "43200"))
SESSION_COOKIE = "contesttrade_session"
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300

HTML = HTML_FILE.read_text(encoding="utf-8") if HTML_FILE.is_file() else ""

_sessions = {}
_login_attempts = {}
_auth_lock = threading.Lock()


def _login_html(error=""):
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ContestTrade 登录</title><style>
*{{box-sizing:border-box}} body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#07101f;color:#e8edf5;font-family:system-ui,sans-serif}}
main{{width:min(92vw,380px);padding:32px;border:1px solid #263651;border-radius:16px;background:#0d192b;box-shadow:0 24px 70px #0008}}
h1{{margin:0 0 8px;color:#e0b35a;font-size:24px}} p{{color:#9dacbf}} label{{display:block;margin:24px 0 8px}}
input{{width:100%;padding:12px;border:1px solid #354967;border-radius:8px;background:#081322;color:#fff;font-size:16px}}
button{{width:100%;margin-top:16px;padding:12px;border:0;border-radius:8px;background:#d5a94f;color:#111;font-weight:700;cursor:pointer}}
.error{{color:#ff8b8b}}
</style></head><body><main><h1>ContestTrade</h1><p>请输入访问密码</p>{error_html}
<form method="post" action="/login"><label for="password">密码</label><input id="password" name="password" type="password" required autofocus autocomplete="current-password"><button type="submit">登录</button></form>
</main></body></html>"""


def _new_session():
    token = secrets.token_urlsafe(32)
    with _auth_lock:
        _sessions[token] = time.time() + SESSION_TTL_SECONDS
    return token


def _session_is_valid(token):
    if not token:
        return False
    now = time.time()
    with _auth_lock:
        expiry = _sessions.get(token, 0)
        if expiry <= now:
            _sessions.pop(token, None)
            return False
        return True



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
    from contest_trade.utils.json_signal_parser import parse_for_web
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

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'",
        )
        super().end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/login":
            if self._is_authenticated():
                self._redirect("/")
            else:
                self._send_html(_login_html())
            return
        if WEB_PASSWORD and not self._is_authenticated():
            if path.startswith("/api/"):
                self._send_json(401, {"error": "authentication required"})
            else:
                self._redirect("/login")
            return
        if path in ("/", "/index.html"):
            self._send_html(HTML)
        elif path == "/api/reports":
            self._list_reports()
        elif path == "/api/health":
            self._get_health()
        elif path == "/api/report":
            self._get_report(parsed.query)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/login":
            self._login()
        elif path == "/logout":
            self._logout()
        else:
            self._send_json(404, {"error": "not found"})

    def _is_authenticated(self):
        if not WEB_PASSWORD:
            return True
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get(SESSION_COOKIE)
        return _session_is_valid(morsel.value if morsel else "")

    def _login(self):
        if not WEB_PASSWORD:
            self._redirect("/")
            return
        client = self.client_address[0]
        now = time.time()
        with _auth_lock:
            attempts = [stamp for stamp in _login_attempts.get(client, []) if now - stamp < LOGIN_WINDOW_SECONDS]
            _login_attempts[client] = attempts
            limited = len(attempts) >= MAX_LOGIN_ATTEMPTS
        if limited:
            self._send_html(_login_html("尝试次数过多，请稍后再试"), 429)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 4096:
            self._send_html(_login_html("请求无效"), 400)
            return
        form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
        supplied = form.get("password", [""])[0]
        if not hmac.compare_digest(supplied, WEB_PASSWORD):
            with _auth_lock:
                _login_attempts.setdefault(client, []).append(now)
            self._send_html(_login_html("密码错误"), 401)
            return
        token = _new_session()
        with _auth_lock:
            _login_attempts.pop(client, None)
        cookie = f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL_SECONDS}"
        self._redirect("/", cookie)

    def _logout(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get(SESSION_COOKIE)
        if morsel:
            with _auth_lock:
                _sessions.pop(morsel.value, None)
        self._redirect("/login", f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")

    def _redirect(self, location, cookie=None):
        self.send_response(303)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _get_health(self):
        try:
            health = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._send_json(503, {"status": "unknown", "message": "no run recorded"})
            return
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            self._send_json(503, {"status": "invalid", "message": str(exc)})
            return

        public_health = {
            "status": health.get("status", "unknown"),
            "trigger_time": health.get("trigger_time"),
            "started_at": health.get("started_at"),
            "finished_at": health.get("finished_at"),
            "duration_seconds": health.get("duration_seconds"),
            "message": health.get("message", ""),
            "metrics": health.get("metrics", {}),
            "report_count": len(health.get("reports", {})),
        }
        code = 200 if public_health["status"] in {"success", "degraded", "running"} else 503
        self._send_json(code, public_health)

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

    def _send_html(self, html, code=200):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[web] {self.address_string()} - {format % args}")


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if HOST not in ("127.0.0.1", "::1", "localhost") and not WEB_PASSWORD:
        raise SystemExit("CONTESTTRADE_WEB_PASSWORD is required when listening on a non-loopback address")
    print(f"📊 ContestTrade 信号终端")
    display_host = "localhost" if HOST in ("127.0.0.1", "::1") else HOST
    print(f"   访问: http://{display_host}:{PORT}")
    print(f"   报告目录: {RESULTS_DIR}")
    print(f"   Ctrl+C 停止")
    if HOST not in ("127.0.0.1", "::1", "localhost"):
        print("⚠️  已显式开启外部监听；请在反向代理层配置 TLS 和访问控制")
    server = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
ContestTrade 报告查看器 - 零依赖单文件 Web 服务

启动: uv run python web/server.py
访问: http://localhost:8765

功能:
- 列出 agents_workspace/results/ 下的所有 markdown 报告
- 点击查看报告内容（markdown 渲染）
- 自动刷新列表（分析运行中能实时看到新报告）
"""
import http.server
import json
import os
import re
import urllib.parse
from pathlib import Path

# ContestTrade 根目录（web/ 的父目录）
ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "contest_trade" / "agents_workspace" / "results"
PORT = 8765

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ContestTrade 报告查看器</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  :root {
    --bg: #0f1419; --panel: #1a2028; --border: #2a3340;
    --text: #e6e6e6; --muted: #8a95a5; --accent: #4a9eff; --accent2: #34d399;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background: var(--bg); color: var(--text); height: 100vh; display: flex; flex-direction: column; }
  header { background: var(--panel); border-bottom: 1px solid var(--border); padding: 12px 20px; display: flex; align-items: center; justify-content: space-between; }
  header h1 { font-size: 16px; font-weight: 600; }
  header .meta { font-size: 12px; color: var(--muted); }
  .main { flex: 1; display: flex; overflow: hidden; }
  .sidebar { width: 320px; background: var(--panel); border-right: 1px solid var(--border); overflow-y: auto; }
  .group-title { padding: 12px 16px 6px; font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }
  .report-item { padding: 10px 16px; border-bottom: 1px solid var(--border); cursor: pointer; transition: background .15s; }
  .report-item:hover { background: rgba(74,158,255,.1); }
  .report-item.active { background: rgba(74,158,255,.15); border-left: 3px solid var(--accent); }
  .report-item .name { font-size: 13px; word-break: break-all; }
  .report-item .time { font-size: 11px; color: var(--muted); margin-top: 3px; }
  .content { flex: 1; overflow-y: auto; padding: 30px 40px; }
  .empty { color: var(--muted); text-align: center; margin-top: 100px; }
  .content h1 { font-size: 22px; margin: 20px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
  .content h2 { font-size: 18px; margin: 18px 0 10px; color: var(--accent2); }
  .content h3 { font-size: 15px; margin: 14px 0 8px; }
  .content p { margin: 8px 0; line-height: 1.7; font-size: 14px; }
  .content ul, .content ol { margin: 8px 0 8px 24px; }
  .content li { margin: 4px 0; line-height: 1.6; font-size: 14px; }
  .content strong { color: var(--accent2); }
  .content hr { border: none; border-top: 1px solid var(--border); margin: 20px 0; }
  .content table { border-collapse: collapse; margin: 10px 0; width: 100%; }
  .content th, .content td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; font-size: 13px; }
  .content th { background: var(--panel); }
  .content code { background: var(--panel); padding: 2px 6px; border-radius: 3px; font-size: 13px; }
  .refresh-indicator { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--accent2); margin-right: 6px; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
</style>
</head>
<body>
<header>
  <h1>📊 ContestTrade 报告查看器</h1>
  <div class="meta"><span class="refresh-indicator"></span><span id="status">加载中...</span></div>
</header>
<div class="main">
  <div class="sidebar" id="sidebar"></div>
  <div class="content" id="content"><div class="empty">选择左侧报告查看<br><br>分析运行中会自动生成新报告</div></div>
</div>
<script>
marked.setOptions({ gfm: true, breaks: false });
let currentPath = null;
async function loadReports() {
  try {
    const r = await fetch('/api/reports');
    const d = await r.json();
    renderSidebar(d.reports);
    document.getElementById('status').textContent = d.reports.length + ' 份报告 · 更新于 ' + new Date().toLocaleTimeString();
  } catch(e) { document.getElementById('status').textContent = '加载失败'; }
}
function renderSidebar(reports) {
  const groups = {};
  reports.forEach(r => {
    const g = r.type === 'research_reports' ? '研究报告' : r.type === 'data_reports' ? '数据报告' : r.type;
    (groups[g] = groups[g] || []).push(r);
  });
  let html = '';
  for (const g of Object.keys(groups)) {
    html += '<div class="group-title">' + g + ' (' + groups[g].length + ')</div>';
    groups[g].forEach(r => {
      const t = new Date(r.mtime * 1000).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});
      const active = r.path === currentPath ? 'active' : '';
      html += '<div class="report-item ' + active + '" data-path="' + r.path + '"><div class="name">' + r.name + '</div><div class="time">' + t + ' · ' + (r.size/1024).toFixed(1) + 'KB</div></div>';
    });
  }
  const sidebar = document.getElementById('sidebar');
  sidebar.innerHTML = html || '<div class="empty" style="margin-top:40px">暂无报告<br><br>分析运行中会自动生成</div>';
  sidebar.querySelectorAll('.report-item').forEach(el => {
    el.addEventListener('click', () => loadReport(el.dataset.path));
  });
}
async function loadReport(path) {
  currentPath = path;
  document.getElementById('content').innerHTML = '<div class="empty">加载中...</div>';
  try {
    const r = await fetch('/api/report?path=' + encodeURIComponent(path));
    const d = await r.json();
    if (d.error) { document.getElementById('content').innerHTML = '<div class="empty">' + d.error + '</div>'; return; }
    document.getElementById('content').innerHTML = marked.parse(d.content);
    document.querySelectorAll('.report-item').forEach(el => {
      el.classList.toggle('active', el.dataset.path === path);
    });
  } catch(e) { document.getElementById('content').innerHTML = '<div class="empty">加载失败</div>'; }
}
loadReports();
setInterval(loadReports, 8000);
</script>
</body>
</html>"""


def safe_resolve(rel_path: str):
    """安全解析相对路径，防止目录穿越。返回绝对路径或 None。"""
    rel_path = (rel_path or "").strip().lstrip("/")
    parts = [p for p in rel_path.split("/") if p not in ("", ".", "..")]
    if not parts:
        return None
    candidate = (RESULTS_DIR / Path(*parts)).resolve()
    results_root = RESULTS_DIR.resolve()
    try:
        candidate.relative_to(results_root)
    except ValueError:
        return None
    return candidate


class Handler(http.server.BaseHTTPRequestHandler):
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
        reports = []
        if RESULTS_DIR.exists():
            for md in RESULTS_DIR.rglob("*.md"):
                rel = md.relative_to(RESULTS_DIR)
                st = md.stat()
                reports.append({
                    "type": str(rel.parts[0]) if len(rel.parts) > 1 else "root",
                    "name": md.name,
                    "path": str(rel),
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                })
        reports.sort(key=lambda x: x["mtime"], reverse=True)
        self._send_json(200, {"reports": reports})

    def _get_report(self, query):
        qs = urllib.parse.parse_qs(query)
        rel_path = qs.get("path", [""])[0]
        full = safe_resolve(rel_path)
        if full is None or not full.is_file() or full.suffix != ".md":
            self._send_json(404, {"error": "报告不存在"})
            return
        try:
            content = full.read_text(encoding="utf-8")
            # 清理项目模板 bug 残留（{self.get_text(...)} 未渲染）
            content = re.sub(r"\{self\.get_text\([^)]*\)\}", "免责声明", content)
            self._send_json(200, {
                "name": full.name,
                "content": content,
                "mtime": full.stat().st_mtime,
            })
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
        pass  # 静默访问日志


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"📊 ContestTrade 报告查看器")
    print(f"   访问: http://localhost:{PORT}")
    print(f"   报告目录: {RESULTS_DIR}")
    print(f"   按 Ctrl+C 停止")
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()

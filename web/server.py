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
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "contest_trade" / "agents_workspace" / "results"
PORT = 8765

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ContestTrade · 信号终端</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  :root {
    /* Claude Desktop 白天暖调 */
    --bg: #F5F4EE;
    --bg-2: #FAF9F5;
    --panel: #FFFFFF;
    --panel-2: #F0EEE6;
    --border: #E8E6DE;
    --border-soft: #EFEEE6;
    --text: #2B2B2B;
    --text-2: #5C5C5C;
    --muted: #8B8B8B;
    --accent: #C96442;
    --accent-soft: #D67755;
    --accent-bg: #F7E9E1;
    --up: #D04848;
    --down: #2E8B6B;
    --warn: #C68235;
    --shadow: 0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.03);
    --shadow-md: 0 4px 12px rgba(0,0,0,0.06), 0 2px 4px rgba(0,0,0,0.04);
    --serif: "Source Serif 4", "Noto Serif SC", "Songti SC", Georgia, serif;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    --mono: "JetBrains Mono", "SF Mono", Menlo, monospace;
    /* 旧变量名别名，指向新色，避免逐处改引用 */
    --gold: var(--accent);
    --gold-soft: var(--accent-soft);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }
  body { font-family: var(--sans); background: var(--bg); color: var(--text); font-size: 15px; line-height: 1.7; -webkit-font-smoothing: antialiased; }

  /* ===== 顶栏 ===== */
  header {
    background: var(--bg-2);
    border-bottom: 1px solid var(--border);
    padding: 18px 36px;
    display: flex; align-items: center; justify-content: space-between;
    position: sticky; top: 0; z-index: 100;
    backdrop-filter: blur(8px);
  }
  .brand { display: flex; align-items: baseline; gap: 14px; }
  .brand .mark { font-family: var(--serif); font-weight: 700; font-size: 22px; letter-spacing: -0.3px; color: var(--text); }
  .brand .mark .accent { color: var(--accent); }
  .brand .sub { font-family: var(--mono); font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 2px; }
  .status { display: flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 11px; color: var(--text-2); }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--down); box-shadow: 0 0 8px rgba(46,139,107,0.5); animation: pulse 2.4s ease-in-out infinite; }
  .dot.idle { background: var(--muted); box-shadow: none; animation: none; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }

  /* ===== 布局 ===== */
  .layout { display: grid; grid-template-columns: 320px 1fr; height: calc(100vh - 65px); }
  .sidebar { background: var(--bg-2); border-right: 1px solid var(--border); overflow-y: auto; }
  .main { overflow-y: auto; }

  /* ===== 侧栏 ===== */
  .side-section { padding: 20px 0; border-bottom: 1px solid var(--border-soft); }
  .side-title { font-family: var(--mono); font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 1.5px; padding: 0 24px 12px; display: flex; justify-content: space-between; align-items: center; }
  .side-title .count { color: var(--accent); font-weight: 600; }
  .report-item { padding: 12px 24px; cursor: pointer; border-left: 2px solid transparent; transition: background .12s, border-color .12s; }
  .report-item:hover { background: var(--panel-2); }
  .report-item.active { background: var(--accent-bg); border-left-color: var(--accent); }
  .report-item .rname { font-size: 13px; color: var(--text); word-break: break-all; line-height: 1.5; }
  .report-item.active .rname { color: var(--accent); font-weight: 500; }
  .report-item .rmeta { font-family: var(--mono); font-size: 10px; color: var(--muted); margin-top: 5px; }
  .report-item .rtype { display: inline-block; font-size: 9px; padding: 1px 6px; border-radius: 3px; background: var(--panel-2); color: var(--text-2); margin-right: 6px; text-transform: uppercase; letter-spacing: 0.5px; }

  /* ===== 主内容 ===== */
  .empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--muted); gap: 14px; }
  .empty-state .glyph { font-family: var(--serif); font-size: 52px; color: var(--border); }
  .empty-state .hint { font-size: 14px; }
  .empty-state .sub-hint { font-family: var(--mono); font-size: 11px; color: var(--muted); }

  /* ===== 报告头 ===== */
  .report-head { padding: 48px 56px 32px; border-bottom: 1px solid var(--border); }
  .rh-eyebrow { font-family: var(--mono); font-size: 11px; color: var(--accent); text-transform: uppercase; letter-spacing: 2px; margin-bottom: 16px; }
  .rh-title { font-family: var(--serif); font-weight: 600; font-size: 34px; line-height: 1.3; letter-spacing: -0.5px; color: var(--text); margin-bottom: 8px; }
  .rh-time { font-family: var(--mono); font-size: 12px; color: var(--muted); margin-bottom: 28px; }

  /* 指标行 - Claude 风格柔和卡片 */
  .metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
  .metric { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px 20px; box-shadow: var(--shadow); }
  .metric .mlabel { font-family: var(--mono); font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }
  .metric .mvalue { font-family: var(--mono); font-size: 24px; font-weight: 600; color: var(--text); margin-top: 6px; }
  .metric .mvalue.gold { color: var(--accent); }
  .metric .mvalue.up { color: var(--up); }

  /* ===== 信号矩阵条（签名元素）===== */
  .matrix-wrap { padding: 32px 56px; border-bottom: 1px solid var(--border); }
  .matrix-label { font-family: var(--mono); font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 14px; display: flex; justify-content: space-between; }
  .matrix { display: flex; gap: 8px; flex-wrap: wrap; }
  .cell { flex: 1; min-width: 84px; padding: 12px 8px; border-radius: 8px; cursor: pointer; position: relative; transition: transform .15s, box-shadow .15s; display: flex; flex-direction: column; align-items: center; justify-content: center; border: 1px solid var(--border); text-align: center; box-shadow: var(--shadow); }
  .cell:hover { transform: translateY(-3px); box-shadow: var(--shadow-md); border-color: var(--accent); }
  .cell .cname { font-family: var(--serif); font-size: 14px; font-weight: 600; color: var(--text); line-height: 1.2; }
  .cell .ccode { font-family: var(--mono); font-size: 9px; color: var(--text-2); opacity: 0.7; margin-top: 4px; }

  /* ===== 信号卡片 ===== */
  .signals { padding: 32px 56px 64px; }
  .signals-title { font-family: var(--serif); font-weight: 600; font-size: 22px; letter-spacing: -0.3px; color: var(--text); margin-bottom: 24px; display: flex; align-items: center; gap: 12px; }
  .signals-title::before { content: ""; width: 28px; height: 2px; background: var(--accent); border-radius: 1px; }

  .signal-card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 20px; overflow: hidden; transition: box-shadow .2s, border-color .2s; box-shadow: var(--shadow); }
  .signal-card:hover { box-shadow: var(--shadow-md); border-color: var(--accent-soft); }
  .sc-head { padding: 20px 26px; border-bottom: 1px solid var(--border-soft); display: flex; align-items: center; gap: 16px; }
  .sc-idx { font-family: var(--mono); font-size: 13px; color: var(--muted); width: 30px; }
  .sc-name { font-family: var(--serif); font-weight: 600; font-size: 22px; letter-spacing: -0.2px; color: var(--text); }
  .sc-code { font-family: var(--mono); font-size: 13px; color: var(--accent); }
  .sc-badges { margin-left: auto; display: flex; gap: 8px; align-items: center; }
  .badge { font-family: var(--mono); font-size: 10px; padding: 4px 10px; border-radius: 12px; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }
  .badge.buy { background: rgba(208,72,72,0.1); color: var(--up); }
  .badge.sell { background: rgba(46,139,107,0.1); color: var(--down); }
  .badge.agent { background: var(--panel-2); color: var(--text-2); }
  .badge.industry { background: transparent; color: var(--text-2); border: 1px solid var(--border); }

  .sc-body { padding: 20px 26px; }
  .sc-section-label { font-family: var(--mono); font-size: 10px; color: var(--accent); text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 14px; }
  .evidence { list-style: none; }
  .evidence li { padding: 12px 0 12px 20px; border-left: 2px solid var(--border); margin-left: 4px; font-size: 14px; line-height: 1.75; color: var(--text-2); position: relative; }
  .evidence li::before { content: ""; position: absolute; left: -5px; top: 18px; width: 8px; height: 8px; border-radius: 50%; background: var(--border); border: 2px solid var(--panel); }
  .evidence li:hover { border-left-color: var(--accent); }
  .evidence li:hover::before { background: var(--accent); }
  .ev-text { color: var(--text); }
  .ev-meta { font-family: var(--mono); font-size: 10px; color: var(--muted); margin-top: 6px; display: flex; gap: 12px; }
  .ev-meta .src { color: var(--accent-soft); }

  .risks { margin-top: 18px; padding-top: 16px; border-top: 1px dashed var(--border); }
  .risk-list { list-style: none; }
  .risk-list li { padding: 7px 0 7px 22px; font-size: 13px; color: var(--text-2); position: relative; line-height: 1.7; }
  .risk-list li::before { content: "⚠"; position: absolute; left: 0; top: 7px; font-size: 11px; color: var(--warn); }

  /* ===== 数据报告 markdown 渲染 ===== */
  .md-report { padding: 48px 56px 64px; max-width: 920px; }
  .md-report h1 { font-family: var(--serif); font-weight: 600; font-size: 28px; letter-spacing: -0.3px; margin: 0 0 8px; color: var(--text); }
  .md-report h2 { font-family: var(--serif); font-weight: 600; font-size: 20px; letter-spacing: -0.2px; margin: 32px 0 12px; color: var(--accent); padding-bottom: 8px; border-bottom: 1px solid var(--border); }
  .md-report h3 { font-family: var(--serif); font-weight: 600; font-size: 17px; margin: 24px 0 10px; color: var(--text); }
  .md-report p { margin: 12px 0; line-height: 1.85; color: var(--text-2); font-size: 15px; }
  .md-report strong { color: var(--text); font-weight: 600; }
  .md-report ul, .md-report ol { margin: 12px 0 12px 24px; }
  .md-report li { margin: 6px 0; line-height: 1.8; color: var(--text-2); font-size: 15px; }
  .md-report hr { border: none; border-top: 1px solid var(--border); margin: 28px 0; }
  .md-report code { font-family: var(--mono); background: var(--panel-2); padding: 2px 6px; border-radius: 4px; font-size: 12px; color: var(--accent); }
  .md-report blockquote { border-left: 3px solid var(--accent); margin: 14px 0; padding: 10px 18px; background: var(--bg-2); color: var(--text-2); border-radius: 0 6px 6px 0; }
  .md-report table { border-collapse: collapse; margin: 14px 0; width: 100%; }
  .md-report th, .md-report td { border: 1px solid var(--border); padding: 10px 14px; text-align: left; font-size: 13px; }
  .md-report th { background: var(--panel-2); color: var(--accent); font-weight: 600; }

  /* ===== 免责 ===== */
  .disclaimer { padding: 28px 56px; border-top: 1px solid var(--border); background: var(--bg-2); font-size: 12px; color: var(--muted); line-height: 1.8; }
  .disclaimer strong { color: var(--text-2); font-family: var(--serif); font-weight: 600; }

  /* ===== 滚动条 ===== */
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 5px; border: 2px solid var(--bg); }
  ::-webkit-scrollbar-thumb:hover { background: var(--muted); }

  /* ===== 响应式 ===== */
  @media (max-width: 768px) {
    .layout { grid-template-columns: 1fr; }
    .sidebar { display: none; }
    .report-head, .matrix-wrap, .signals, .disclaimer, .md-report { padding-left: 24px; padding-right: 24px; }
    .metrics { grid-template-columns: repeat(2, 1fr); }
    .rh-title { font-size: 24px; }
  }
  @media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }
  :focus-visible { outline: 2px solid var(--gold); outline-offset: 2px; }
</style>
</head>
<body>
<header>
  <div class="brand">
    <div class="mark">Contest<span class="accent">Trade</span></div>
    <div class="sub">Signal Terminal</div>
  </div>
  <div class="status"><span class="dot" id="dot"></span><span id="status">连接中</span></div>
</header>
<div class="layout">
  <aside class="sidebar" id="sidebar"></aside>
  <main class="main" id="main">
    <div class="empty-state">
      <div class="glyph">◆</div>
      <div class="hint">选择左侧报告查看信号</div>
      <div class="sub-hint">分析运行中将自动刷新</div>
    </div>
  </main>
</div>
<script>
let currentPath = null;
marked.setOptions({ gfm: true, breaks: false });

async function loadReports() {
  try {
    const r = await fetch('/api/reports');
    const d = await r.json();
    renderSidebar(d.reports);
    const n = d.reports.length;
    document.getElementById('status').textContent = n + ' 份报告 · ' + new Date().toLocaleTimeString('zh-CN');
    document.getElementById('dot').classList.toggle('idle', n === 0);
  } catch(e) {
    document.getElementById('status').textContent = '连接失败';
    document.getElementById('dot').classList.add('idle');
  }
}

function renderSidebar(reports) {
  const groups = {};
  reports.forEach(r => {
    const g = r.type === 'research_reports' ? '研究报告' : r.type === 'data_reports' ? '数据报告' : r.type;
    (groups[g] = groups[g] || []).push(r);
  });
  let html = '';
  for (const g of Object.keys(groups)) {
    html += '<div class="side-section"><div class="side-title"><span>' + g + '</span><span class="count">' + groups[g].length + '</span></div>';
    groups[g].forEach(r => {
      const t = new Date(r.mtime * 1000).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
      const active = r.path === currentPath ? 'active' : '';
      const tlabel = r.type === 'research_reports' ? 'RES' : 'DATA';
      html += '<div class="report-item ' + active + '" data-path="' + r.path + '"><div class="rname"><span class="rtype">' + tlabel + '</span>' + r.name + '</div><div class="rmeta">' + t + ' · ' + (r.size/1024).toFixed(1) + 'KB</div></div>';
    });
    html += '</div>';
  }
  const sb = document.getElementById('sidebar');
  sb.innerHTML = html || '<div class="empty-state" style="height:200px"><div class="sub-hint">暂无报告</div></div>';
  sb.querySelectorAll('.report-item').forEach(el => {
    el.addEventListener('click', () => loadReport(el.dataset.path));
  });
}

async function loadReport(path) {
  currentPath = path;
  document.getElementById('main').innerHTML = '<div class="empty-state"><div class="hint">加载中…</div></div>';
  document.querySelectorAll('.report-item').forEach(el => el.classList.toggle('active', el.dataset.path === path));
  try {
    const r = await fetch('/api/report?path=' + encodeURIComponent(path) + '&structured=1');
    const d = await r.json();
    if (d.error) { renderError(d.error); return; }
    if (d.structured && d.structured.signals) {
      renderStructured(d.structured);
    } else if (d.structured && d.structured.agents) {
      renderDataReport(d.structured, d.name);
    } else {
      renderFallback(d.content, d.name);
    }
  } catch(e) { renderError('加载失败'); }
}

function renderError(msg) {
  document.getElementById('main').innerHTML = '<div class="empty-state"><div class="glyph">◇</div><div class="hint">' + msg + '</div></div>';
}

function renderDataReport(s, name) {
  // 数据报告：按数据 agent 分组渲染，剥掉开头元信息
  const agents = s.agents || [];
  let html = '<div class="report-head"><div class="rh-eyebrow">数据分析 · 4 个数据源</div>';
  html += '<div class="rh-title">数据源分析详情</div>';
  html += '<div class="rh-time">' + name.replace('.md','').replace(/_/g,' ') + ' · 各数据 agent 摘要</div></div>';
  html += '<div class="signals"><div class="signals-title">数据 Agent 摘要</div>';
  agents.forEach((ag, i) => {
    html += '<div class="signal-card"><div class="sc-head"><div class="sc-idx">' + String(i+1).padStart(2,'0') + '</div>';
    html += '<div class="sc-name">' + ag.name + '</div>';
    html += '<div class="sc-badges"><span class="badge agent">DATA AGENT</span></div></div>';
    html += '<div class="sc-body"><div class="md-report" style="padding:0;max-width:none">' + marked.parse(ag.body) + '</div></div></div>';
  });
  html += '</div>';
  html += '<div class="disclaimer"><strong>免责声明</strong>　本报告由 ContestTrade AI 系统生成，仅供学术研究，不构成任何投资建议。数据源可能存在延迟或不准确，投资有风险，入市需谨慎。</div>';
  document.getElementById('main').innerHTML = html;
}

function renderFallback(content, name) {
  // 数据报告：用 marked 渲染 markdown，套用 .md-report 样式
  const html = marked.parse(content);
  const wrap = '<div class="report-head"><div class="rh-eyebrow">数据报告</div><div class="rh-title">' + name.replace('.md','').replace(/_/g,' ') + '</div></div>';
  document.getElementById('main').innerHTML = wrap + '<div class="md-report">' + html + '</div>';
}

// 行业推断（用于矩阵条着色）
function inferIndustry(text) {
  const t = text.toLowerCase();
  if (/半导体|芯片|光模块|中微|北方华创|中芯|晶圆|集成电路/.test(t)) return {name:'半导体', color:'#4A7FD6'};
  if (/石油|原油|油气|海油|石化|能源/.test(t)) return {name:'能源', color:'#D4943B'};
  if (/黄金|贵金属|矿业|锆|有色|小金属/.test(t)) return {name:'资源', color:'#A569C9'};
  if (/茅台|白酒|消费|食品/.test(t)) return {name:'消费', color:'#D04848'};
  if (/保险|银行|券商|金融|太保|人寿/.test(t)) return {name:'金融', color:'#2E8B6B'};
  if (/光伏|储能|锂电|新能源|阳光电源|通威/.test(t)) return {name:'新能源', color:'#3BAFA1'};
  return {name:'其他', color:'#8B8B8B'};
}

function renderStructured(s) {
  const m = s.metrics || {};
  const sigs = s.signals || [];
  let html = '';

  // 报告头
  html += '<div class="report-head">';
  html += '<div class="rh-eyebrow">ContestTrade 信号报告 · ' + (m.time || '') + '</div>';
  html += '<div class="rh-title">事件驱动选股 · ' + sigs.length + ' 个信号</div>';
  html += '<div class="rh-time">分析时间 ' + (m.time || '—') + ' · 数据源 ' + (m.data_sources || '4') + ' · 有效率 ' + (m.valid_rate || '100%') + '</div>';
  html += '<div class="metrics">';
  html += metric('信号总数', m.signal_count || sigs.length, 'gold');
  html += metric('有效信号', m.valid_count || sigs.length, 'up');
  html += metric('数据源', m.data_sources || '4', '');
  html += metric('有效率', m.valid_rate || '100%', 'up');
  html += '</div></div>';

  // 信号矩阵条
  if (sigs.length) {
    html += '<div class="matrix-wrap">';
    html += '<div class="matrix-label"><span>信号矩阵 · 按行业分布</span><span>' + sigs.length + ' 个标的</span></div>';
    html += '<div class="matrix">';
    sigs.forEach((sg, i) => {
      const ind = inferIndustry(sg.name + ' ' + (sg.evidence||[]).join(' '));
      html += '<div class="cell" style="background:' + ind.color + '1A;border-color:' + ind.color + '55" title="' + sg.name + ' (' + sg.code + ') · ' + ind.name + ' · #' + (i+1) + '" data-idx="' + i + '"><div class="cname">' + (sg.name || '-') + '</div><div class="ccode">' + (sg.code || '') + '</div></div>';
    });
    html += '</div></div>';
  }

  // 信号卡片
  html += '<div class="signals"><div class="signals-title">投资信号</div>';
  sigs.forEach((sg, i) => {
    const ind = inferIndustry(sg.name + ' ' + (sg.evidence||[]).join(' '));
    const action = (sg.action||'buy').toLowerCase();
    html += '<div class="signal-card" id="sig-' + i + '">';
    html += '<div class="sc-head"><div class="sc-idx">' + String(i+1).padStart(2,'0') + '</div>';
    html += '<div class="sc-name">' + (sg.name || '—') + '</div>';
    html += '<div class="sc-code">' + (sg.code || '') + '</div>';
    html += '<div class="sc-badges">';
    html += '<span class="badge industry">' + ind.name + '</span>';
    html += '<span class="badge agent">' + (sg.agent || '') + '</span>';
    html += '<span class="badge ' + action + '">' + (action === 'buy' ? '买入' : '卖出') + '</span>';
    html += '</div></div>';
    html += '<div class="sc-body">';
    if (sg.evidence && sg.evidence.length) {
      html += '<div class="sc-section-label">支撑证据 · ' + sg.evidence.length + ' 项</div>';
      html += '<ul class="evidence">';
      sg.evidence.forEach(ev => {
        html += '<li><div class="ev-text">' + (ev.text || '') + '</div>';
        html += '<div class="ev-meta"><span class="src">' + (ev.source || '') + '</span><span>' + (ev.time || '') + '</span></div></li>';
      });
      html += '</ul>';
    }
    if (sg.risks && sg.risks.length) {
      html += '<div class="risks"><div class="sc-section-label" style="color:var(--warn)">风险提示</div><ul class="risk-list">';
      sg.risks.forEach(rk => { html += '<li>' + rk + '</li>'; });
      html += '</ul></div>';
    }
    html += '</div></div>';
  });
  html += '</div>';

  // 免责
  html += '<div class="disclaimer"><strong>免责声明</strong>　本报告由 ContestTrade AI 系统生成，仅供学术研究，不构成任何投资建议。AI 模型存在幻觉风险，数据源可能延迟或不准确。投资有风险，入市需谨慎。</div>';

  document.getElementById('main').innerHTML = html;
  // 矩阵点击跳转
  document.querySelectorAll('.cell').forEach(c => {
    c.addEventListener('click', () => {
      const el = document.getElementById('sig-' + c.dataset.idx);
      if (el) el.scrollIntoView({behavior:'smooth', block:'start'});
    });
  });
}

function metric(label, value, cls) {
  return '<div class="metric"><div class="mlabel">' + label + '</div><div class="mvalue ' + cls + '">' + value + '</div></div>';
}

loadReports();
setInterval(loadReports, 8000);
</script>
</body>
</html>"""


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


def parse_structured(content: str) -> dict:
    """把研究报告 markdown 解析成结构化信号数据，供前端卡片渲染。"""
    result = {"metrics": {}, "signals": []}

    # 指标
    m = re.search(r"分析时间\*\*:\s*([^\n]+)", content)
    if m:
        result["metrics"]["time"] = m.group(1).strip()
    m = re.search(r"数据源数量\*\*:\s*(\d+)", content)
    if m:
        result["metrics"]["data_sources"] = m.group(1).strip()
    m = re.search(r"研究信号数量\*\*:\s*(\d+)", content)
    if m:
        result["metrics"]["signal_count"] = m.group(1).strip()
    m = re.search(r"有效投资信号\*\*:\s*(\d+)", content)
    if m:
        result["metrics"]["valid_count"] = m.group(1).strip()
    m = re.search(r"信号有效率\*\*:\s*([\d.]+%)", content)
    if m:
        result["metrics"]["valid_rate"] = m.group(1).strip()

    # 按信号标题分块: #### 1. 名称 (代码)
    signal_blocks = re.split(r"\n####\s*\d+\.\s*", content)
    for block in signal_blocks[1:]:  # 第一段是前言
        sig = {"name": "", "code": "", "action": "buy", "agent": "", "evidence": [], "risks": []}
        # 首行: 名称 (代码)
        first_line = block.split("\n", 1)[0].strip()
        nm = re.match(r"(.+?)\s*\(([^)]+)\)", first_line)
        if nm:
            sig["name"] = nm.group(1).strip()
            sig["code"] = nm.group(2).strip()
        else:
            sig["name"] = first_line

        # 动作
        am = re.search(r"投资动作\*\*:\s*(\w+)", block)
        if am:
            sig["action"] = am.group(1).strip().lower()
        # 来源
        ag = re.search(r"分析来源\*\*:\s*(.+)", block)
        if ag:
            sig["agent"] = ag.group(1).strip()

        # 证据: 每条以数字. 开头，结尾是 (来源: xxx, 时间: xxx)
        ev_section = re.search(r"支撑证据.*?:\s*\n(.*?)(?=\n- \*\*风险|\Z)", block, flags=re.DOTALL)
        if ev_section:
            for ev_match in re.finditer(r"\d+\.\s*\*\*(.+?)\*\*\s*\((来源:|来源：)(.+?)\)", ev_section.group(1), flags=re.DOTALL):
                text = ev_match.group(1).strip()
                meta = ev_match.group(3).strip()
                src, t = "", ""
                sm = re.search(r"(.+?)[:,，]\s*时间[:：]\s*(.+)", meta)
                if sm:
                    src = sm.group(1).strip()
                    t = sm.group(2).strip()
                else:
                    src = meta
                sig["evidence"].append({"text": text, "source": src, "time": t})

        # 风险: 风险提示后到下一个 #### / 免责声明 / 末尾
        risk_section = re.search(r"风险提示\*\*:\s*\n(.*?)(?=\n####|\n##\s|免责声明|\Z)", block, flags=re.DOTALL)
        if risk_section:
            for line in risk_section.group(1).split("\n"):
                line = re.sub(r"^\s*[-•]\s*", "", line).strip()
                # 跳过纯分隔线/标点行
                if line and not re.fullmatch(r"[-_=*~]+", line):
                    sig["risks"].append(line)

        if sig["name"]:
            result["signals"].append(sig)

    return result


def parse_data_report(content: str) -> dict:
    """把数据报告 markdown 解析成按数据 agent 分组的结构化数据。
    剥掉开头元信息(标题/数据摘要/数据源分析详情)，每个 agent 的摘要正文 markdown 保留。"""
    result = {"agents": []}
    # 截取"数据源分析详情"之后的内容（跳过开头元信息）
    m = re.search(r"数据源分析详情\s*\n(.+?)(?=\n##\s*⚠|免责声明|\Z)", content, flags=re.DOTALL)
    body = m.group(1) if m else content
    # 按 ### 📈 XXX Agent 分块（用多行模式 ^ 匹配，避免漏掉首个 agent）
    blocks = re.split(r"^###\s+[📈📊🔍💡]?\s*", body, flags=re.MULTILINE)
    for block in blocks:
        if not block.strip():
            continue
        lines = block.split("\n", 1)
        agent_name = lines[0].strip()
        agent_body = lines[1].strip() if len(lines) > 1 else ""
        # 去掉 agent 摘要里重复的 "# 市场信息综合摘要" 和孤立的 "时间：xxx" 行
        agent_body = re.sub(r"^#\s*市场信息综合摘要\s*\n+", "", agent_body)
        agent_body = re.sub(r"^\*\*时间[：:].*?\*\*\s*\n+", "", agent_body, flags=re.MULTILINE)
        # 清理 LongCat 检索残留: "Documents: Title: xxx Publish Time: xxx Content:  😐..." 前缀
        agent_body = re.sub(r"^Documents:\s*Title:[^\n]*\nPublish Time:[^\n]*\nContent:\s*", "", agent_body)
        if agent_name and agent_body:
            result["agents"].append({"name": agent_name, "body": agent_body})
    return result


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
        want_structured = qs.get("structured", ["0"])[0] == "1"
        full = safe_resolve(rel_path)
        if full is None or not full.is_file() or full.suffix != ".md":
            self._send_json(404, {"error": "报告不存在"})
            return
        try:
            content = full.read_text(encoding="utf-8")
            content = re.sub(r"\{self\.get_text\([^)]*\)\}", "免责声明", content)
            data = {"name": full.name, "content": content, "mtime": full.stat().st_mtime}
            # 研究报告提供结构化解析
            if want_structured and "research_reports" in rel_path:
                data["structured"] = parse_structured(content)
            elif want_structured and "data_reports" in rel_path:
                data["structured"] = parse_data_report(content)
                data["report_type"] = "data"
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

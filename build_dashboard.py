# -*- coding: utf-8 -*-
"""
每日指标看板生成器（手机友好，交互式 HTML，供 GitHub Pages 发布）

2026-10-30 交互版 v2（前端评审 P0 修复）：
  · 单标的 H20269 红利低波全收益指数（策略阈值与历史检验均在它上面标定）；
  · 图表改为客户端 JS 绘制：数据只内嵌一份，三图 x 轴共享同一数组；
    顶部时间范围按钮（近3月/1年/2年/5年/全部，带激活态）+ 拖拽/双指/滚轮缩放，
    三图 x 轴同步联动，y 轴按可见窗口自动收紧（纵轴固定为派生量，手势只作用于时间轴）；
  · 触屏：拖动=平移（不再与页面滚动语义冲突），双击图表=复位当前视图；
  · 「跌破年线」红底纹按数据区段绘制（yref=paper 全高），图例条目为纯说明、
    点击不会隐藏底纹（plotly_legendclick 返回 false 拦截）；
  · 乖离率图 y 轴自适应时自动并入邻近的策略阈值线（卖50%/清仓线不再凭空消失）；
  · 数据过期自检：数据日期落后查看日 ≥4 天时，页首红条提醒重新构建；
  · 窄屏（≤620px）图例自动移到图表下方，不再遮挡曲线；标题改用 HTML 标签不再截断；
  · 体积：plotly-basic 精简包（~1.1MB）替代全量包（4.5MB），数据数组只存一份。
每日重建由 .github/workflows/update-page.yml 自动完成（拉主仓库数据→重建→提交，
Pages 随仓库刷新），人工只需在改了图表代码时才需要本地构建。

读取：主项目 data/H20269历史数据.csv（中证官网 API 维护，只追加）
输出：index.html（写入本目录）
用法：python build_dashboard.py
"""
# === 数据源定位（兼容本地副项目布局 与 GitHub Actions 布局） ===
import os as _os
import sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
# 候选 1（CI）：workflow 把数据仓库 checkout 到本目录下的同名子目录
# 候选 2（本地）：本目录位于 红利低波_副项目/03_在线看板，数据仓库在同级的爷爷目录
_ROOT = None
for _cand in (_os.path.join(_HERE, '红利低波价格走势分析程序'),
              _os.path.abspath(_os.path.join(_HERE, '..', '..', '红利低波价格走势分析程序'))):
    if _os.path.isdir(_cand):
        _ROOT = _cand
        break
if _ROOT is None:
    raise SystemExit('找不到数据目录 红利低波价格走势分析程序（本地或 CI checkout 均未就位）')
for _p in (_ROOT, _HERE):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
if _os.path.abspath(_os.getcwd()) != _ROOT:
    _os.chdir(_ROOT)
# === /数据源定位 ===

import json
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

OUT_PATH = _os.path.join(_HERE, 'index.html')


def _pick_plotly():
    """客户端图表库：优先本地精简包（basic ~1.1MB，覆盖 scatter/shapes/图例全部所需），
    缺失时退回本地全量包 / CDN。"""
    for name in ('plotly-basic.min.js', 'plotly.min.js'):
        if _os.path.exists(_os.path.join(_HERE, name)):
            return './' + name
    return 'https://cdn.plot.ly/plotly-basic-2.35.2.min.js'


PLOTLY_JS = _pick_plotly()

# 策略/信号阈值（与 core/rolling_position_backtest.py 及 docs/ROLLING_POSITION_STRATEGY.md 对齐）
TIER3, TIER2 = -8.0, -4.0        # 深度定投 3×/2× 触发线（乖离率%）
SELL_A, SELL_B = 15.0, 17.5      # 年线策略 卖出50%/清仓线（乖离率%）
WATCH = 4.5                      # 中期止盈观察区（从年线下方反弹至 +4.5%）

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def beijing_now():
    return datetime.now(timezone(timedelta(hours=8)))


# ------------------------------------------------------------- 指标计算 ----

def compute_indicators(df):
    """与 core/data_calculator.py 同口径：MA/乖离率/RSI(Wilder)。"""
    df = df.sort_values('日期').reset_index(drop=True).copy()
    for w in (20, 60, 120, 250):
        df[f'MA{w}'] = df['收盘'].rolling(w).mean()
    df['乖离率'] = (df['收盘'] - df['MA250']) / df['MA250'] * 100
    df['bias20'] = (df['收盘'] - df['MA20']) / df['MA20'] * 100
    for n in (6, 12, 24):
        delta = df['收盘'].diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
        rs = gain / loss.clip(lower=1e-6)
        df[f'RSI{n}'] = (100 - 100 / (1 + rs)).clip(0.01, 99.99)
    return df


def compute_signals(df):
    """三个中期止盈信号 + 观察区（2026-10 历史检验定义，见 DASHBOARD_GUIDE.md）。"""
    s = pd.DataFrame(index=df.index)
    rsi6_max15 = df['RSI6'].rolling(15).max()
    s['S1'] = ((df['收盘'] >= df['收盘'].rolling(20).max() * 0.999)
               & (rsi6_max15.shift(1) >= 78)
               & (df['RSI6'] <= rsi6_max15.shift(1) - 8))
    s['S2'] = ((df['RSI6'].shift(1) >= 60) & (df['RSI6'] < 60)
               & (df['RSI6'].rolling(12).max().shift(1) >= 80))
    s['S3'] = ((df['收盘'].shift(1) >= df['MA20'].shift(1)) & (df['收盘'] < df['MA20'])
               & (df['乖离率'].rolling(10).max() >= 4.0)
               & (df['乖离率'].rolling(90).min() < 0))
    s['S4'] = (df['乖离率'] >= WATCH) & (df['乖离率'].rolling(90).min() < 0)
    return s


def last_fire(sig_series, df, within_days=(5, 15)):
    idx = sig_series.fillna(False).values
    last_i = None
    for i in range(len(idx) - 1, -1, -1):
        if idx[i]:
            last_i = i
            break
    if last_i is None:
        return 'off', '—'
    age = len(idx) - 1 - last_i
    state = 'active' if age <= within_days[0] else ('warm' if age <= within_days[1] else 'off')
    return state, df['日期'].iloc[last_i].strftime('%Y-%m-%d')


def zone_of(bias):
    if bias <= TIER3:
        return '深度定投3×区', 'z3x'
    if bias <= TIER2:
        return '深度定投2×区', 'z2x'
    if bias < 0:
        return '年线下方 · 定投观察', 'zbelow'
    if bias < SELL_A:
        return '年线上方 · 持有', 'zhold'
    if bias <= SELL_B:
        return '触发卖出50%线', 'zsell'
    return '触发清仓线', 'zclear'


# ------------------------------------------------------------- 数据序列 ----

def _below_segments(d):
    """收盘跌破 MA250 的连续区段 [(起索引, 止索引), ...]（闭区间、相对 d 的行号）。"""
    below = (d['收盘'] < d['MA250']).values
    segs, in_seg, start = [], False, 0
    for i in range(len(d)):
        if below[i] and not in_seg:
            in_seg, start = True, i
        if in_seg and (not below[i] or i == len(d) - 1):
            segs.append([start, i if below[i] else i - 1])
            in_seg = False
    return segs


def _js_arr(s):
    """数值 Series → JS 数组字面量；NaN 写作 null（图表断点，纵轴拟合时跳过）。"""
    vals = [None if v != v else round(float(v), 2) for v in s]
    return '[' + ','.join('null' if v is None else repr(v) for v in vals) + ']'


# ------------------------------------------------------------- 页面 ----

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
       background: #f4f6f8; color: #2c3e50; padding-bottom: 40px; }
.wrap { max-width: 860px; margin: 0 auto; padding: 14px; }
h1 { font-size: 20px; margin: 8px 0 2px; }
.meta { font-size: 12px; color: #5d6d7e; margin-bottom: 10px; }
.stale { background: #fdf0ef; border-left: 4px solid #e74c3c; color: #943126;
         font-size: 12px; line-height: 1.6; padding: 10px 12px; border-radius: 8px;
         margin: 10px 0; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
         gap: 8px; margin: 10px 0; }
.card { background: #fff; border-radius: 10px; padding: 10px 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.card .k { font-size: 11px; color: #5d6d7e; margin-bottom: 4px; }
.card .v { font-size: 19px; font-weight: 600; }
.card .v small { font-size: 11px; color: #5d6d7e; font-weight: normal; }
.badge { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 10px;
         color: #fff; margin-top: 4px; }
.z3x{background:#21618c}.z2x{background:#2e86c1}.zbelow{background:#ca8a04}
.zhold{background:#1e8449}.zsell{background:#d35400}.zclear{background:#922b21}
.zonebar { position: relative; height: 16px; border-radius: 8px; margin: 18px 2px 26px;
  background: linear-gradient(90deg,#21618c 0%,#2e86c1 12.5%,#ca8a04 25%,#1e8449 43.75%,
              #d35400 84.4%,#922b21 100%); }
.zonebar .pin { position: absolute; top: -22px; transform: translateX(-50%);
  font-size: 15px; color: #2c3e50; }
.zonebar .cur { position: absolute; top: 22px; transform: translateX(-50%);
  font-size: 11px; color: #2c3e50; white-space: nowrap; font-weight: 600; }
.zonebar .tick { position: absolute; top: 16px; font-size: 9px; color: #5d6d7e;
  transform: translateX(-50%); }
.sig { display: grid; grid-template-columns: repeat(auto-fit, minmax(158px, 1fr));
       gap: 8px; margin: 10px 0 4px; }
.sigcard { background: #fff; border-radius: 10px; padding: 9px 12px;
           box-shadow: 0 1px 3px rgba(0,0,0,.08); border-left: 4px solid #bdc3c7; }
.sigcard.active { border-left-color: #e74c3c; background: #fdf0ef; }
.sigcard.warm { border-left-color: #f39c12; background: #fef9f0; }
.sigcard .row { display: flex; justify-content: space-between; align-items: center;
                gap: 6px; }
.sigcard .t { font-size: 12px; font-weight: 600; display: flex; align-items: center;
              white-space: nowrap; }
.sigcard .chip { font-size: 10px; padding: 1px 7px; border-radius: 9px; color: #fff;
                 background: #95a5a6; white-space: nowrap; flex: none; }
.chip.active { background: #e74c3c; }
.chip.warm { background: #f39c12; }
.sigcard .d { font-size: 11px; color: #5d6d7e; margin-top: 4px;
              font-variant-numeric: tabular-nums; }
.sigcard .d b { color: #2c3e50; font-weight: 600; }
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%;
       margin-right: 5px; background: #bdc3c7; flex: none; }
.active .dot { background: #e74c3c; animation: blink 1.2s infinite; }
.warm .dot { background: #f39c12; }
@keyframes blink { 50% { opacity: .35; } }
.rgbtns { display: flex; gap: 6px; margin: 14px 0 2px; flex-wrap: wrap;
          align-items: center; }
.rgbtns .lab { font-size: 12px; color: #5d6d7e; margin-right: 2px; }
.rgbtns button { font-size: 12px; padding: 5px 12px; border: 1px solid #d0d7de;
  background: #fff; border-radius: 16px; cursor: pointer; color: #2c3e50; }
.rgbtns button:active { background: #eef2f6; }
.rgbtns button.active { background: #2c3e50; color: #fff; border-color: #2c3e50; }
.rgbtns button:focus-visible { outline: 2px solid #2c3e50; outline-offset: 1px; }
.hint { font-size: 11px; color: #5d6d7e; margin: 2px 2px 4px; }
.chart { background: #fff; border-radius: 10px; padding: 6px 4px 2px; margin: 10px 0;
         box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.chart h3 { font-size: 14px; font-weight: 600; color: #2c3e50; margin: 8px 12px 0; }
.plot { width: 100%; }
.tablewrap { overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 10px 0;
             border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
table { width: 100%; border-collapse: collapse; background: #fff; font-size: 12px;
        min-width: 520px; }
th, td { padding: 6px 8px; text-align: right; }
th:nth-child(1), td:nth-child(1), th:last-child, td:last-child { text-align: left; }
th { background: #ecf0f1; font-weight: 600; }
tr:nth-child(even) td { background: #fafbfc; }
.pos { color: #c0392b; } .neg { color: #1e8449; }
.foot { font-size: 12px; color: #5d6d7e; line-height: 1.7; margin-top: 20px;
        background: #fff; border-radius: 10px; padding: 12px 14px;
        box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.foot b { color: #2c3e50; }
"""

ZONE_TICKS = [(TIER3, '-8'), (TIER2, '-4'), (0, '0'), (WATCH, '+4.5'),
              (SELL_A, '+15'), (SELL_B, '+17.5')]

# 客户端全部图表逻辑：见 sync_js 与 init 块（数据由 assemble_html 注入
# window.__dates / __S / __seg / __asOf，三图共享同一日期数组，零冗余）。
SYNC_JS = """
'use strict';
var D = window.__dates;
var S = window.__S;
var T = D.map(function (s) { return Date.parse(s); });
var IDS = ['c_price', 'c_bias', 'c_rsi'];
var lastApply = 0, btnRange = null, btnKey = null;
var CFG = { responsive: true, displayModeBar: false, scrollZoom: true };
var MARGIN = {
  c_price: { l: 52, r: 14, t: 6, b: 26 },
  c_bias:  { l: 46, r: 48, t: 6, b: 26 },
  c_rsi:   { l: 46, r: 14, t: 6, b: 26 }
};
var TH = [
  { v: -8.0, c: '#2980b9', t: '3×定投' },
  { v: -4.0, c: '#5dade2', t: '2×定投' },
  { v: 0,    c: '#7f8c8d', t: '年线' },
  { v: 4.5,  c: '#f39c12', t: '止盈观察' },
  { v: 15.0, c: '#e67e22', t: '卖50%' },
  { v: 17.5, c: '#c0392b', t: '清仓' }
];

function toTs(v) { return typeof v === 'number' ? v : Date.parse(v); }
function bs(x) {
  var lo = 0, hi = T.length - 1, r = T.length - 1;
  while (lo <= hi) {
    var mid = (lo + hi) >> 1;
    if (T[mid] >= x) { r = mid; hi = mid - 1; } else { lo = mid + 1; }
  }
  return r;
}
function idxRange(r) {
  var i0 = bs(toTs(r[0])), i1 = bs(toTs(r[1]));
  if (i1 <= i0) i1 = Math.min(T.length - 1, i0 + 1);
  return [i0, i1];
}
function dateEnd() { return D[D.length - 1]; }
function dateNDaysAgo(days) {
  return days > 0
    ? new Date(Date.parse(dateEnd()) - days * 86400000).toISOString().slice(0, 10)
    : D[0];
}
function legendOpts() {
  return window.innerWidth <= 620
    ? { orientation: 'h', x: 0, xanchor: 'left', y: -0.18, yanchor: 'top', font: { size: 10 } }
    : { orientation: 'h', x: 0, xanchor: 'left', y: 1, yanchor: 'bottom', font: { size: 11 } };
}
function applyLegendPos() {
  var below = window.innerWidth <= 620;
  IDS.forEach(function (id) {
    var m = Object.assign({}, MARGIN[id]);
    m.b = below ? 62 : MARGIN[id].b;
    Plotly.relayout(document.getElementById(id), { legend: legendOpts(), margin: m });
  });
}
function segShapes() {
  return window.__seg.map(function (s) {
    return { type: 'rect', xref: 'x', yref: 'paper', layer: 'below',
             x0: D[s[0]], x1: D[s[1]], y0: 0, y1: 1,
             fillcolor: 'rgba(200,60,60,0.12)', line: { width: 0 } };
  });
}
var DOC = { x: [null], y: [null], mode: 'lines', hoverinfo: 'skip', isDoc: true,
            name: '跌破年线区间（红底纹）',
            line: { color: 'rgba(200,60,60,0.5)', width: 10 } };

function buildPrice() {
  var traces = [
    { x: D, y: S.close, name: '收盘', mode: 'lines',
      line: { color: '#1f77b4', width: 1.8 } },
    { x: D, y: S.ma20, name: 'MA20', mode: 'lines',
      line: { color: '#ff7f0e', width: 1.1 } },
    { x: D, y: S.ma60, name: 'MA60', mode: 'lines',
      line: { color: '#2ca02c', width: 1.1 } },
    { x: D, y: S.ma250, name: 'MA250', mode: 'lines',
      line: { color: '#d62728', width: 1.6 } },
    DOC
  ];
  var layout = {
    height: 400, margin: MARGIN.c_price, hovermode: 'x unified', dragmode: 'pan',
    legend: legendOpts(),
    xaxis: { range: [dateNDaysAgo(730), dateEnd()], doubleclick: 'false' },
    yaxis: { tickformat: ',.0f', fixedrange: true, doubleclick: 'false' },
    shapes: segShapes()
  };
  Plotly.newPlot('c_price', traces, layout, CFG);
}
function buildBias() {
  var shapes = TH.map(function (o) {
    return { type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y',
             y0: o.v, y1: o.v, line: { color: o.c, width: 1, dash: 'dot' },
             layer: 'below' };
  });
  var annos = TH.map(function (o) {
    return { xref: 'paper', yref: 'y', x: 1, y: o.v, xanchor: 'left',
             yanchor: 'middle', text: o.t, font: { size: 9, color: o.c },
             showarrow: false, xshift: 3, align: 'left' };
  });
  var traces = [{ x: D, y: S.bias, name: '年线乖离率%', mode: 'lines',
                  line: { color: '#636efa', width: 1.5 }, fill: 'tozeroy',
                  fillcolor: 'rgba(99,110,250,0.10)' }];
  var layout = {
    height: 300, margin: MARGIN.c_bias, hovermode: 'x unified', dragmode: 'pan',
    showlegend: false,
    xaxis: { range: [dateNDaysAgo(730), dateEnd()], doubleclick: 'false' },
    yaxis: { range: [-12, 20], fixedrange: true, doubleclick: 'false' },
    shapes: shapes, annotations: annos
  };
  Plotly.newPlot('c_bias', traces, layout, CFG);
}
function buildRsi() {
  var traces = [
    { x: D, y: S.rsi6, name: 'RSI6', mode: 'lines',
      line: { color: '#e74c3c', width: 1.3 } },
    { x: D, y: S.rsi12, name: 'RSI12', mode: 'lines',
      line: { color: '#27ae60', width: 1.3 } },
    { x: D, y: S.rsi24, name: 'RSI24', mode: 'lines',
      line: { color: '#8e44ad', width: 1.3 } }
  ];
  var shapes = [30, 70].map(function (v) {
    return { type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: v, y1: v,
             line: { color: '#7f8c8d', width: 1, dash: 'dot' }, layer: 'below' };
  });
  var layout = {
    height: 280, margin: MARGIN.c_rsi, hovermode: 'x unified', dragmode: 'pan',
    legend: legendOpts(),
    xaxis: { range: [dateNDaysAgo(730), dateEnd()], doubleclick: 'false' },
    yaxis: { range: [0, 100], fixedrange: true, doubleclick: 'false' },
    shapes: shapes
  };
  Plotly.newPlot('c_rsi', traces, layout, CFG);
}

function fitSlice(i0, i1, arrs) {
  var mn = Infinity, mx = -Infinity;
  arrs.forEach(function (arr) {
    for (var i = i0; i <= i1; i++) {
      var v = arr[i];
      if (v != null && isFinite(v)) {
        if (v < mn) mn = v;
        if (v > mx) mx = v;
      }
    }
  });
  return isFinite(mn) ? [mn, mx] : null;
}
function relayoutY(id, lo, hi) {
  Plotly.relayout(document.getElementById(id), { 'yaxis.range': [lo, hi] });
}
function refitPrice(r) {
  var p = fitSlice.apply(null, idxRange(r).concat([[S.close, S.ma20, S.ma60, S.ma250]]));
  if (!p) return;
  var span = (p[1] - p[0]) || Math.abs(p[1]) || 1;
  relayoutY('c_price', p[0] - span * 0.06, p[1] + span * 0.06);
}
function refitBias(r) {
  var p = fitSlice.apply(null, idxRange(r).concat([[S.bias]]));
  if (!p) return;
  var lo = p[0], hi = p[1], span = (hi - lo) || Math.abs(hi) || 1;
  TH.forEach(function (o) {
    if (o.v > hi && o.v - hi < span * 0.45) hi = o.v;   // 邻近阈值线并入视野
    if (o.v < lo && lo - o.v < span * 0.45) lo = o.v;
  });
  span = (hi - lo) || 1;
  relayoutY('c_bias', lo - span * 0.10, hi + span * 0.10);
}
function setActive(btnKey) {
  var buttons = document.querySelectorAll('.rgbtns button[data-days]');
  Array.prototype.forEach.call(buttons, function (b) {
    var on = btnKey != null && b.getAttribute('data-days') === String(btnKey);
    b.classList.toggle('active', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
}
function applyRange(r, btnKey) {
  lastApply = Date.now();
  IDS.forEach(function (id) {
    Plotly.relayout(document.getElementById(id), { 'xaxis.range': r });
  });
  refitPrice(r); refitBias(r);
  setActive(btnKey);
}
function setRange(days, el) {
  var r = [dateNDaysAgo(days), dateEnd()];
  btnRange = r;                                   // 记住按钮范围，供双击复位
  btnKey = el ? el.getAttribute('data-days') : null;
  applyRange(r, btnKey);
}
function resetView() {
  if (btnRange) applyRange(btnRange, btnKey);     // 回到最近一次按钮选择的范围
  else setRange(730, document.querySelector('.rgbtns button[data-days="730"]'));
}

var readyDone = false;
var initTries = 0;
function bindAndStart() {
  IDS.forEach(function (id) {
    var el = document.getElementById(id);
    el.on('plotly_relayout', function (ev) {
      if (Date.now() - lastApply < 80) return;
      var r = ev['xaxis.range'];
      if (!r && ev['xaxis.range[0]']) r = [ev['xaxis.range[0]'], ev['xaxis.range[1]']];
      if (!r) return;
      // 按天取整，并夹在数据范围内（平移不越界）
      var t0 = Math.max(toTs(r[0]), Date.parse(D[0]));
      var t1 = Math.min(toTs(r[1]), Date.parse(dateEnd()));
      if (t1 - t0 < 86400000) return;
      applyRange([new Date(t0).toISOString().slice(0, 10),
                  new Date(t1).toISOString().slice(0, 10)], null);
    });
    el.on('plotly_legendclick', function (pt) {
      return pt.data && pt.data.isDoc ? false : undefined;  // 说明条目：点击不隐藏底纹
    });
    // 捕获阶段注册：先于 plotly 内部 dblclick 处理器，避免被 stopImmediatePropagation 吞掉
    el.addEventListener('dblclick', resetView, true);
  });
  setRange(730, document.querySelector('.rgbtns button[data-days="730"]'));
  readyDone = true;
  applyLegendPos();
}
// 轮询式自愈初始化：newPlot 偶发被中断时不会抛错、只是没画出来，
// 轮询发现未画满 3 张就自动重画一次兜底，画好才绑定事件并设定初始范围。
(function waitReady() {
  try {
    var plotted = document.querySelectorAll('.js-plotly-plot').length;
    if (plotted < 3) {
      if (++initTries === 10) { buildPrice(); buildBias(); buildRsi(); }
      if (initTries < 60) setTimeout(waitReady, 150);
      return;
    }
    bindAndStart();
  } catch (e) {
    if (++initTries < 60) setTimeout(waitReady, 150);
  }
})();
var rzT = null;
window.addEventListener('resize', function () {
  clearTimeout(rzT);
  rzT = setTimeout(function () { if (readyDone) applyLegendPos(); }, 200);
});

// 数据过期自检：数据日期落后查看日 ≥4 天时提醒重建
(function () {
  var days = Math.floor((Date.now() - Date.parse(window.__asOf)) / 86400000);
  if (days >= 4) {
    var el = document.getElementById('stale');
    el.textContent = '⚠ 数据截至 ' + window.__asOf + '（' + days + ' 天前）。'
      + '请在主项目仓库执行 git pull 后运行 build_dashboard.py 重新生成并推送，'
      + '或等待看板仓库的每日自动重建。';
    el.hidden = false;
  }
})();
"""


def pos_pct(bias):
    return max(0.0, min(100.0, (bias + 12.0) / 32.0 * 100))


def cards_html(df):
    last = df.iloc[-1]
    bias = last['乖离率']
    tone = 'pos' if bias >= 0 else 'neg'
    return f"""
    <div class="cards">
      <div class="card"><div class="k">最新收盘</div>
        <div class="v">{last['收盘']:,.2f}<small> {last['日期'].strftime('%m-%d')}</small></div></div>
      <div class="card"><div class="k">年线乖离率</div>
        <div class="v {tone}">{bias:+.2f}%</div>
        <span class="badge {zone_of(bias)[1]}">{zone_of(bias)[0]}</span></div>
      <div class="card"><div class="k">RSI 6 / 12 / 24</div>
        <div class="v">{last['RSI6']:.0f}<small> / </small>{last['RSI12']:.0f}<small> / </small>{last['RSI24']:.0f}</div></div>
      <div class="card"><div class="k">距 MA20 / MA60</div>
        <div class="v">{last['bias20']:+.1f}%<small> / </small>
        {(last['收盘']/last['MA60']-1)*100:+.1f}%</div></div>
    </div>"""


def zonebar_html(bias):
    p = pos_pct(bias)
    ticks = ''.join(f'<span class="tick" style="left:{pos_pct(v):.1f}%">{t}</span>'
                    for t, v in [(t, v) for v, t in ZONE_TICKS])
    return f"""
    <div class="zonebar">
      <span class="pin" style="left:{p:.1f}%">▼</span>
      <span class="cur" style="left:{p:.1f}%">{bias:+.2f}%</span>
      {ticks}
    </div>"""


def sig_cards_html(df, sig):
    defs = [('S1', 'RSI6 顶背离'), ('S2', 'RSI6 超买回落'), ('S3', '跌破MA20确认')]
    chips = {'active': '触发中', 'warm': '近期出现', 'off': '未触发'}
    out = ''
    for key, label in defs:
        state, date = last_fire(sig[key], df)
        out += (f'<div class="sigcard {state}">'
                f'<div class="row"><span class="t"><span class="dot"></span>{label}</span>'
                f'<span class="chip {state}">{chips[state]}</span></div>'
                f'<div class="d">最近触发 <b>{date}</b></div></div>')
    state, date = last_fire(sig['S4'], df)
    now_on = bool(sig['S4'].iloc[-1])
    card_state = 'active' if now_on else state
    chip = '观察中' if now_on else chips[state]
    out += (f'<div class="sigcard {card_state}">'
            f'<div class="row"><span class="t"><span class="dot"></span>中期止盈观察区</span>'
            f'<span class="chip {card_state}">{chip}</span></div>'
            f'<div class="d">最近进入 <b>{date}</b></div></div>')
    return out


def table_html(df, sig):
    tail20 = df.tail(20).iloc[::-1]
    rows = ''
    for _, r in tail20.iterrows():
        fired = [k for k in ('S1', 'S2', 'S3') if sig[k].loc[r.name]]
        rows += (f"<tr><td>{r['日期'].strftime('%Y-%m-%d')}</td>"
                 f"<td>{r['收盘']:,.2f}</td>"
                 f"<td class=\"{'pos' if r['乖离率']>0 else 'neg'}\">{r['乖离率']:+.2f}</td>"
                 f"<td>{r['RSI6']:.0f}</td><td>{r['RSI12']:.0f}</td>"
                 f"<td>{'+'.join(fired) if fired else ''}</td></tr>")
    return (f'<div class="tablewrap"><table><tr><th>日期</th><th>收盘</th>'
            f'<th>乖离率%</th><th>RSI6</th><th>RSI12</th><th>信号</th></tr>'
            f'{rows}</table></div>')


def section(df):
    sig = compute_signals(df)
    bias = df.iloc[-1]['乖离率']
    return (cards_html(df) + zonebar_html(bias)
            + '<div class="sig">' + sig_cards_html(df, sig) + '</div>'
            + '<div class="rgbtns"><span class="lab">时间范围（三图联动）：</span>'
              '<button data-days="90" onclick="setRange(90,this)">近3月</button>'
              '<button data-days="365" onclick="setRange(365,this)">近1年</button>'
              '<button data-days="730" class="active" aria-pressed="true" '
              'onclick="setRange(730,this)">近2年</button>'
              '<button data-days="1825" onclick="setRange(1825,this)">近5年</button>'
              '<button data-days="0" onclick="setRange(0,this)">全部</button></div>'
            + '<div class="hint">拖动=平移 · 双指/滚轮=缩放 · 双击图表=复位视图 · '
              '点图例名可隐藏/显示均线（红底纹说明条目除外）</div>'
            + '<div class="chart"><h3>价格与均线 · H20269 红利低波全收益指数</h3>'
              '<div id="c_price" class="plot"></div></div>'
              '<div class="chart"><h3>年线乖离率（收盘相对 MA250）</h3>'
              '<div id="c_bias" class="plot"></div></div>'
              '<div class="chart"><h3>RSI（Wilder 平滑，30/70 参考线）</h3>'
              '<div id="c_rsi" class="plot"></div></div>'
            + table_html(df, sig))


FOOT = """
<div class="foot">
<b>口径与信号定义</b><br>
· 看板标的：<b>H20269 红利低波全收益指数</b>。策略阈值与历史检验全部在它上面标定；
  实盘交易的 512890 与其 2019 年以来日收益相关 0.979、年化差约 1.2pp（打新增厚），
  走势基本同步；阈值不适用于价格指数 H30269（与全收益年化差约 5.7pp）。<br>
· 年线乖离率 = (收盘 − MA250) / MA250 × 100%；RSI 为 Wilder 平滑（与本项目 core/data_calculator.py 同口径）。<br>
· 策略区间：≤−8% 深度定投3×；−8%~−4% 深度定投2×；&lt;0 年线下方；0~+15% 持有；&gt;+15% 卖出50%；&gt;+17.5% 清仓（年线主策略）。<br>
· S1 顶背离：收盘创20日新高而 15 日内 RSI6 高点(≥78)回落 8 点以上；S2 超买回落：12 日内 RSI6 曾≥80 后跌破 60；
S3 破位确认：反弹情景下（90 日内乖离率曾&lt;0、10 日内曾≥+4%）收盘跌破 MA20；观察区：自年线下方反弹至 ≥+4.5%。<br>
· 历史检验（H20269，2007–2026，18 次独立事件）：自年线下方反弹至 +4.5% 后，61% 最终先触及 +15% 卖出线，
仅 2015-11、2022-11 两次直接回落——中期信号宜作<b>分批减仓/停止加仓</b>参考，不宜全仓了结。详见 DASHBOARD_GUIDE.md。<br>
· 价格图中<b>红色底纹 = 收盘跌破年线（MA250）的区间</b>；图例中同名条目仅为说明，点击不会隐藏底纹。<br>
· 数据源：中证指数官网 API（H20269，收盘后更新）。本页为研究工具，不构成投资建议。
</div>
"""


def assemble_html(idx, source_note=''):
    """把单标的指标 DataFrame 组装成完整看板 HTML（静态构建与实时渲染共用）。"""
    if idx['MA250'].iloc[-1] != idx['MA250'].iloc[-1]:  # NaN 检查
        raise RuntimeError('H20269: 最新一日 MA250 为空，数据不足')
    dd = idx.dropna(subset=['MA250', 'RSI6'])
    now = beijing_now()
    asof = idx['日期'].iloc[-1].strftime('%Y-%m-%d')
    note = f' · {source_note}' if source_note else ''
    data_js = (
        'window.__asOf=' + json.dumps(asof) + ';\n'
        'window.__dates=' + json.dumps([d.strftime('%Y-%m-%d') for d in dd['日期']]) + ';\n'
        'window.__seg=' + json.dumps(_below_segments(dd)) + ';\n'
        'window.__S={close:' + _js_arr(dd['收盘'])
        + ',ma20:' + _js_arr(dd['MA20'])
        + ',ma60:' + _js_arr(dd['MA60'])
        + ',ma250:' + _js_arr(dd['MA250'])
        + ',bias:' + _js_arr(dd['乖离率'])
        + ',rsi6:' + _js_arr(dd['RSI6'])
        + ',rsi12:' + _js_arr(dd['RSI12'])
        + ',rsi24:' + _js_arr(dd['RSI24']) + '};'
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>红利低波 · 每日指标看板</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='18' fill='%232c3e50'/><text x='50' y='70' font-size='54' text-anchor='middle'>📈</text></svg>">
<style>{CSS}</style>
<script src="{PLOTLY_JS}"></script>
</head>
<body>
<div class="wrap">
<h1>红利低波 · 每日指标看板</h1>
<div class="meta">H20269 红利低波全收益指数 · 数据截至 {asof} 收盘 · 生成于 {now.strftime('%Y-%m-%d %H:%M')}（北京时间）{note}</div>
<div id="stale" class="stale" hidden></div>
{section(idx)}
{FOOT}
</div>
<script>{data_js}</script>
<script>{SYNC_JS}</script>
</body>
</html>"""


def main():
    idx = compute_indicators(pd.read_csv('data/H20269历史数据.csv', encoding='utf-8-sig'))
    idx['日期'] = pd.to_datetime(idx['日期'])
    html = assemble_html(idx)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'已生成 {OUT_PATH}（{len(html)/1024:.0f} KB）')
    print(f'H20269 乖离率 {idx["乖离率"].iloc[-1]:+.2f}% | '
          f'RSI6 {idx["RSI6"].iloc[-1]:.1f} | 数据末行 {idx["日期"].iloc[-1].date()}')


if __name__ == '__main__':
    main()

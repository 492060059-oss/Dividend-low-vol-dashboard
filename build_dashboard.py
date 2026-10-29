# -*- coding: utf-8 -*-
"""
每日指标看板生成器（手机友好，交互式 HTML，供 GitHub Pages 发布）

2026-10-30 交互版：
  · 单标的 H20269 红利低波全收益指数（策略阈值与历史检验均在它上面标定；
    512890 与其走势一致但含打新增厚，不再单独展示）；
  · 价格与均线 / 年线乖离率 / RSI 三张图全部输出全历史数据，
    支持顶部按钮（近1年/2年/5年/全部）与拖拽缩放，三图 x 轴同步联动；
  · 「跌破年线」区间改为红色底纹 + 图例条目说明，不再使用图内文字标注。

读取：data/H20269历史数据.csv（主项目 data/，中证官网 API 维护，只追加）
输出：index.html（写入本目录）—— 静态快照，双击可看；发布见 DASHBOARD_GUIDE.md
用法：python build_dashboard.py（建议先在主项目 git pull 拿到最新数据）
"""
# === 数据源定位（副项目版） ===
import os as _os
import sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.abspath(_os.path.join(_HERE, '..', '..', '红利低波价格走势分析程序'))
for _p in (_ROOT, _HERE):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
if _os.path.abspath(_os.getcwd()) != _ROOT:
    _os.chdir(_ROOT)
# === /数据源定位 ===

import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go

OUT_PATH = _os.path.join(_HERE, 'index.html')

# plotly.min.js 本地优先（GitHub Pages 同源加载最稳），缺失时退回 CDN
_PLOTLY_LOCAL = _os.path.join(_HERE, 'plotly.min.js')
PLOTLY_JS = './plotly.min.js' if _os.path.exists(_PLOTLY_LOCAL) else \
    'https://cdn.plot.ly/plotly-2.35.2.min.js'

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


# ------------------------------------------------------------- 图表 ----
# 三张图共用同一份全历史 x 轴（MA250/RSI 均有效的区间），保证联动缩放严格对齐。

_CFG = {'responsive': True, 'displayModeBar': False, 'scrollZoom': True}


def _below_segments(d):
    """收盘跌破 MA250 的连续区间 [(起始日, 结束日), ...]。"""
    below = (d['收盘'] < d['MA250']).values
    segs, in_seg, start = [], False, None
    for i in range(len(d)):
        if below[i] and not in_seg:
            in_seg, start = True, i
        if in_seg and (not below[i] or i == len(d) - 1):
            end = i if below[i] else i - 1
            segs.append((d['日期'].iloc[start], d['日期'].iloc[end]))
            in_seg = False
    return segs


def _dates(d):
    return d['日期'].dt.strftime('%Y-%m-%d').tolist()


def _js_arr(s):
    """Series → JS 数组字面量（NaN 直接写作 NaN，浏览器端可解析）。"""
    vals = [None if v != v else round(float(v), 2) for v in s]
    return '[' + ','.join('null' if v is None else repr(v) for v in vals) + ']'


def _tail_range(d, cols, n, pad, include_zero=False):
    """末 n 行各列的最小/最大值（y 轴初始可见范围）。"""
    tail = d.tail(n)
    vals = pd.concat([tail[c] for c in cols]).dropna()
    lo, hi = float(vals.min()), float(vals.max())
    span = (hi - lo) or abs(hi) or 1.0
    lo, hi = lo - span * pad, hi + span * pad
    if include_zero:
        lo = min(lo, 0.0)
    return [lo, hi]


def fig_price(d, initial_n):
    x = _dates(d)
    fig = go.Figure()
    fig.add_scatter(x=x, y=d['收盘'].round(2), name='收盘',
                    line=dict(color='#1f77b4', width=1.8))
    for col, color, width in [('MA20', '#ff7f0e', 1.1), ('MA60', '#2ca02c', 1.1),
                              ('MA250', '#d62728', 1.6)]:
        fig.add_scatter(x=x, y=d[col].round(2), name=col,
                        line=dict(color=color, width=width))
    # 跌破年线 → 纯色底纹（不加图内文字），含义由图例条目说明
    for s, e in _below_segments(d):
        fig.add_vrect(x0=s, x1=e, fillcolor='rgba(200,60,60,0.12)',
                      line_width=0, layer='below')
    fig.add_scatter(x=[None], y=[None], mode='lines', hoverinfo='skip',
                    name='跌破年线区间（红底纹）',
                    line=dict(color='rgba(200,60,60,0.5)', width=10))
    fig.update_layout(title='价格与均线 · H20269 红利低波全收益指数',
                      height=400, margin=dict(l=46, r=16, t=46, b=28),
                      legend=dict(orientation='h', y=1.06, x=0, font_size=10),
                      hovermode='x unified', xaxis_range=[x[-initial_n], x[-1]],
                      yaxis_range=_tail_range(d, ['收盘', 'MA20', 'MA60', 'MA250'],
                                              initial_n, 0.06))
    fig.update_yaxes(tickformat=',.0f')
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       div_id='c_price', config=_CFG)


def fig_bias(d, initial_n):
    x = _dates(d)
    fig = go.Figure()
    fig.add_scatter(x=x, y=d['乖离率'].round(2), name='年线乖离率%',
                    line=dict(color='#636efa', width=1.5), fill='tozeroy',
                    fillcolor='rgba(99,110,250,0.10)')
    for y, color, text in [(TIER3, '#2980b9', '3×定投'), (TIER2, '#5dade2', '2×定投'),
                           (0, '#7f8c8d', '年线'), (WATCH, '#f39c12', '止盈观察'),
                           (SELL_A, '#e67e22', '卖50%'), (SELL_B, '#c0392b', '清仓')]:
        fig.add_hline(y=y, line_dash='dot', line_color=color, line_width=1,
                      annotation_text=text, annotation_font_size=9,
                      annotation_font_color=color, annotation_position='right')
    fig.update_layout(title='年线乖离率（收盘相对 MA250）',
                      height=300, margin=dict(l=46, r=52, t=46, b=28),
                      showlegend=False, hovermode='x unified',
                      xaxis_range=[x[-initial_n], x[-1]],
                      yaxis_range=_tail_range(d, ['乖离率'], initial_n, 0.12, True))
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       div_id='c_bias', config=_CFG)


def fig_rsi(d, initial_n):
    x = _dates(d)
    fig = go.Figure()
    for col, color in [('RSI6', '#e74c3c'), ('RSI12', '#27ae60'), ('RSI24', '#8e44ad')]:
        fig.add_scatter(x=x, y=d[col].round(1), name=col,
                        line=dict(color=color, width=1.3))
    fig.add_hline(y=30, line_dash='dot', line_color='#7f8c8d', line_width=1)
    fig.add_hline(y=70, line_dash='dot', line_color='#7f8c8d', line_width=1)
    fig.update_layout(title='RSI（Wilder 平滑，30/70 参考线）',
                      height=280, margin=dict(l=46, r=16, t=46, b=28),
                      legend=dict(orientation='h', y=1.08, x=0, font_size=10),
                      hovermode='x unified', yaxis_range=[0, 100],
                      xaxis_range=[x[-initial_n], x[-1]])
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       div_id='c_rsi', config=_CFG)


# ------------------------------------------------------------- 页面 ----

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
       background: #f4f6f8; color: #2c3e50; padding-bottom: 40px; }
.wrap { max-width: 860px; margin: 0 auto; padding: 14px; }
h1 { font-size: 20px; margin: 8px 0 2px; }
.meta { font-size: 12px; color: #7f8c8d; margin-bottom: 10px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
         gap: 8px; margin: 10px 0; }
.card { background: #fff; border-radius: 10px; padding: 10px 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.card .k { font-size: 11px; color: #95a5a6; margin-bottom: 4px; }
.card .v { font-size: 19px; font-weight: 600; }
.card .v small { font-size: 11px; color: #95a5a6; font-weight: normal; }
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
.zonebar .tick { position: absolute; top: 16px; font-size: 9px; color: #7f8c8d;
  transform: translateX(-50%); }
.sig { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
       gap: 8px; margin: 10px 0 4px; }
.sigcard { background: #fff; border-radius: 10px; padding: 9px 12px;
           box-shadow: 0 1px 3px rgba(0,0,0,.08); border-left: 4px solid #bdc3c7; }
.sigcard.active { border-left-color: #e74c3c; background: #fdf0ef; }
.sigcard.warm { border-left-color: #f39c12; background: #fef9f0; }
.sigcard .t { font-size: 12px; font-weight: 600; }
.sigcard .d { font-size: 11px; color: #7f8c8d; margin-top: 3px; }
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%;
       margin-right: 5px; background: #bdc3c7; }
.active .dot { background: #e74c3c; animation: blink 1.2s infinite; }
.warm .dot { background: #f39c12; }
@keyframes blink { 50% { opacity: .35; } }
.rgbtns { display: flex; gap: 6px; margin: 14px 0 2px; flex-wrap: wrap;
          align-items: center; }
.rgbtns .lab { font-size: 12px; color: #7f8c8d; margin-right: 2px; }
.rgbtns button { font-size: 12px; padding: 5px 12px; border: 1px solid #d0d7de;
  background: #fff; border-radius: 16px; cursor: pointer; color: #2c3e50; }
.rgbtns button:active { background: #eef2f6; }
.chart { background: #fff; border-radius: 10px; padding: 6px 4px; margin: 10px 0;
         box-shadow: 0 1px 3px rgba(0,0,0,.08); }
table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px;
        overflow: hidden; font-size: 12px; margin: 10px 0;
        box-shadow: 0 1px 3px rgba(0,0,0,.08); }
th, td { padding: 6px 8px; text-align: right; }
th:nth-child(1), td:nth-child(1), th:last-child, td:last-child { text-align: left; }
th { background: #ecf0f1; font-weight: 600; }
tr:nth-child(even) td { background: #fafbfc; }
.pos { color: #c0392b; } .neg { color: #1e8449; }
.foot { font-size: 12px; color: #7f8c8d; line-height: 1.7; margin-top: 20px;
        background: #fff; border-radius: 10px; padding: 12px 14px;
        box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.foot b { color: #2c3e50; }
"""

ZONE_TICKS = [(TIER3, '-8'), (TIER2, '-4'), (0, '0'), (WATCH, '+4.5'),
              (SELL_A, '+15'), (SELL_B, '+17.5')]

SYNC_JS = """
var IDS = ['c_price', 'c_bias', 'c_rsi'];
var lastApply = 0;
function __bs(arr, x) {
  var lo = 0, hi = arr.length - 1, r = arr.length - 1;
  while (lo <= hi) {
    var mid = (lo + hi) >> 1;
    if (arr[mid] >= x) { r = mid; hi = mid - 1; } else { lo = mid + 1; }
  }
  return r;
}
function refitY(id, fit) {
  var gd = document.getElementById(id);
  var r = gd.layout.xaxis.range;
  if (!r || !fit) return;
  var i0 = __bs(fit.t, new Date(r[0]).getTime());
  var i1 = __bs(fit.t, new Date(r[1]).getTime());
  if (i1 <= i0) i1 = Math.min(fit.t.length - 1, i0 + 1);
  var mn = Infinity, mx = -Infinity;
  fit.y.forEach(function (arr) {
    for (var i = i0; i <= i1; i++) {
      var v = arr[i];
      if (v != null && isFinite(v)) {
        if (v < mn) mn = v;
        if (v > mx) mx = v;
      }
    }
  });
  if (!isFinite(mn) || !isFinite(mx)) return;
  var span = (mx - mn) || Math.abs(mx) || 1;
  var lo = mn - span * fit.pad, hi = mx + span * fit.pad;
  if (fit.zero) lo = Math.min(lo, 0);
  Plotly.relayout(gd, { 'yaxis.range': [lo, hi] });
}
function applyAll(range) {
  lastApply = Date.now();
  IDS.forEach(function (id) {
    Plotly.relayout(document.getElementById(id), {'xaxis.range': range});
  });
  refitY('c_price', window.__fitPrice);
  refitY('c_bias', window.__fitBias);
}
function setRange(days) {
  var d = window.__dates;
  if (!d || !d.length) return;
  var end = d[d.length - 1];
  var start = days > 0
    ? new Date(new Date(end).getTime() - days * 86400000).toISOString().slice(0, 10)
    : d[0];
  applyAll([start, end]);
}
IDS.forEach(function (id) {
  var el = document.getElementById(id);
  el.on('plotly_relayout', function (ev) {
    if (Date.now() - lastApply < 80) return;
    var r = ev['xaxis.range'];
    if (!r && ev['xaxis.range[0]']) r = [ev['xaxis.range[0]'], ev['xaxis.range[1]']];
    if (!r) return;
    applyAll(r);
  });
});
"""


def pos_pct(bias):
    return max(0.0, min(100.0, (bias + 12.0) / 32.0 * 100))


def section(df):
    sig = compute_signals(df)
    last = df.iloc[-1]
    bias = last['乖离率']
    zone_name, zone_cls = zone_of(bias)

    cards = f"""
    <div class="cards">
      <div class="card"><div class="k">最新收盘</div>
        <div class="v">{last['收盘']:,.2f}<small> {last['日期'].strftime('%m-%d')}</small></div></div>
      <div class="card"><div class="k">年线乖离率</div>
        <div class="v">{bias:+.2f}%</div>
        <span class="badge {zone_cls}">{zone_name}</span></div>
      <div class="card"><div class="k">RSI 6 / 12 / 24</div>
        <div class="v">{last['RSI6']:.0f}<small> / </small>{last['RSI12']:.0f}<small> / </small>{last['RSI24']:.0f}</div></div>
      <div class="card"><div class="k">距 MA20 / MA60</div>
        <div class="v">{last['bias20']:+.1f}%<small> / </small>
        {(last['收盘']/last['MA60']-1)*100:+.1f}%</div></div>
    </div>"""

    ticks = ''.join(f'<span class="tick" style="left:{pos_pct(v):.1f}%">{t}</span>'
                    for t, v in [(t, v) for v, t in ZONE_TICKS])
    zonebar = f"""
    <div class="zonebar">
      <span class="pin" style="left:{pos_pct(bias):.1f}%">▼</span>
      <span class="cur" style="left:{pos_pct(bias):.1f}%">{bias:+.2f}%</span>
      {ticks}
    </div>"""

    defs = [('S1', 'RSI6 顶背离'), ('S2', 'RSI6 超买回落'), ('S3', '跌破MA20确认')]
    sigcards = ''
    for key, label in defs:
        state, date = last_fire(sig[key], df)
        state_cn = {'active': '● 触发中（近5日）', 'warm': '○ 近期出现', 'off': '— 未触发'}[state]
        sigcards += (f'<div class="sigcard {state}"><div class="t"><span class="dot"></span>'
                     f'{label}</div><div class="d">{state_cn} · 最近 {date}</div></div>')
    s4_state, s4_date = last_fire(sig['S4'], df)
    s4_now = '● 已进入观察区' if bool(sig['S4'].iloc[-1]) else '— 未处于观察区'
    sigcards += (f'<div class="sigcard {"active" if bool(sig["S4"].iloc[-1]) else ""}">'
                 f'<div class="t"><span class="dot"></span>中期止盈观察区</div>'
                 f'<div class="d">{s4_now} · 最近进入 {s4_date}</div></div>')

    tail20 = df.tail(20).iloc[::-1]
    rows = ''
    for _, r in tail20.iterrows():
        fired = [k for k in ('S1', 'S2', 'S3') if sig[k].loc[r.name]]
        rows += (f"<tr><td>{r['日期'].strftime('%Y-%m-%d')}</td>"
                 f"<td>{r['收盘']:,.2f}</td>"
                 f"<td class=\"{'pos' if r['乖离率']>0 else 'neg'}\">{r['乖离率']:+.2f}</td>"
                 f"<td>{r['RSI6']:.0f}</td><td>{r['RSI12']:.0f}</td>"
                 f"<td>{'+'.join(fired) if fired else ''}</td></tr>")
    table = (f'<table><tr><th>日期</th><th>收盘</th><th>乖离率%</th><th>RSI6</th>'
             f'<th>RSI12</th><th>信号</th></tr>{rows}</table>')

    return (cards + zonebar +
            '<div class="sig">' + sigcards + '</div>' +
            '<div class="rgbtns"><span class="lab">时间范围（三图联动）：</span>'
            '<button onclick="setRange(90)">近3月</button>'
            '<button onclick="setRange(365)">近1年</button>'
            '<button onclick="setRange(730)">近2年</button>'
            '<button onclick="setRange(1825)">近5年</button>'
            '<button onclick="setRange(0)">全部</button></div>'
            f'<div class="chart">{fig_price(df, 500)}</div>'
            f'<div class="chart">{fig_bias(df, 1250)}</div>'
            f'<div class="chart">{fig_rsi(df, 250)}</div>' +
            table)


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
· 价格图中<b>红色底纹 = 收盘跌破年线（MA250）的区间</b>，见图例「跌破年线区间」。<br>
· 数据源：中证指数官网 API（H20269，收盘后更新）。本页为研究工具，不构成投资建议。
</div>
"""


def assemble_html(idx, source_note=''):
    """把单标的指标 DataFrame 组装成完整看板 HTML（静态构建与实时渲染共用）。"""
    if idx['MA250'].iloc[-1] != idx['MA250'].iloc[-1]:  # NaN 检查
        raise RuntimeError('H20269: 最新一日 MA250 为空，数据不足')
    global dd
    dd = idx.dropna(subset=['MA250', 'RSI6'])
    now = beijing_now()
    asof = idx['日期'].iloc[-1].strftime('%Y-%m-%d')
    note = f' · {source_note}' if source_note else ''
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>红利低波 · 每日指标看板</title>
<style>{CSS}</style>
<script src="{PLOTLY_JS}"></script>
</head>
<body>
<div class="wrap">
<h1>红利低波 · 每日指标看板</h1>
<div class="meta">H20269 红利低波全收益指数 · 数据截至 {asof} 收盘 · 生成于 {now.strftime('%Y-%m-%d %H:%M')}（北京时间）{note}</div>
{section(idx)}
{FOOT}
</div>
<script>
window.__dates = {_dates(dd)};
window.__fitPrice = {{
  t: window.__dates.map(function (s) {{ return new Date(s).getTime(); }}),
  y: [{_js_arr(dd['收盘'])}, {_js_arr(dd['MA20'])}, {_js_arr(dd['MA60'])}, {_js_arr(dd['MA250'])}],
  pad: 0.06, zero: false}};
window.__fitBias = {{
  t: window.__fitPrice.t,
  y: [{_js_arr(dd['乖离率'])}],
  pad: 0.12, zero: true}};
</script>
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

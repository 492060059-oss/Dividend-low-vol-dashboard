# -*- coding: utf-8 -*-
"""
看板实时渲染：现场拉取最新数据 → 复用 build_dashboard 渲染 HTML。

与静态流程（update_data.py 落盘 + build_dashboard.py 读盘）不同，本模块不落盘，
每次调用直接联网取数并计算，供 dashboard_app.py（Web 服务，Render 免费实例部署）
调用。数据链路有三层兜底：

    H20269:  中证官网API(拉约5年) -> 主项目 data/H20269历史数据.csv
    512890:  东财前复权 -> 腾讯分段 -> 主项目 data/512890行情数据.csv

结果缓存 10 分钟（TTL），避免频繁刷新打爆数据源。
"""
# === 数据源定位（副项目版） ===
# 本文件已从主项目（交易系统仓库）拆出：数据兜底读主项目 data/ 两个 CSV，
# update_data 从主项目 scripts/data/ 导入；可在任意工作目录调用。
import os as _os
import sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.abspath(_os.path.join(_HERE, '..', '..', '红利低波价格走势分析程序'))
for _p in (_ROOT, _os.path.join(_ROOT, 'scripts', 'data'), _HERE):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
if _os.path.abspath(_os.getcwd()) != _ROOT:
    _os.chdir(_ROOT)
# === /数据源定位 ===

import time

import pandas as pd

import build_dashboard as bd   # noqa: E402  (本目录已挂入 sys.path)
import update_data as ud       # noqa: E402  (主项目 scripts/data/ 已挂入 sys.path)

# 拉约 5 年半：MA250 需 250 日 + RSI(Wilder ewm) 预热收敛 + 近2年图表窗口，足够
HISTORY_START = '20210101'
CACHE_TTL = 600  # 秒

_cache = {'html': None, 'ts': 0.0}


def fetch_h20269_live():
    """中证官网 API，返回 DataFrame(日期, 收盘)。"""
    end = ud.beijing_now().strftime('%Y%m%d')
    url = ('https://www.csindex.com.cn/csindex-home/perf/index-perf'
           f'?indexCode=H20269&startDate={HISTORY_START}&endDate={end}')
    payload = ud.fetch_json(url, headers={'Referer': 'https://www.csindex.com.cn/'})
    rows = payload.get('data') or []
    if len(rows) < 300:
        raise RuntimeError(f'csindex 返回行数异常: {len(rows)}')
    df = pd.DataFrame({
        '日期': pd.to_datetime([r['tradeDate'] for r in rows]),
        '收盘': [float(r['close']) for r in rows],
    })
    return df.sort_values('日期').reset_index(drop=True)


def _load_csv(path):
    df = pd.read_csv(path, encoding='utf-8-sig')
    df['日期'] = pd.to_datetime(df['日期'])
    return df[['日期', '收盘']]


def get_dashboard_html(force=False):
    """实时渲染看板 HTML（带 10 分钟缓存）。API 全挂时退回仓库 CSV。"""
    if not force and _cache['html'] and time.time() - _cache['ts'] < CACHE_TTL:
        return _cache['html']

    notes = []
    try:
        idx_raw = fetch_h20269_live()
    except Exception:
        idx_raw = _load_csv('data/H20269历史数据.csv')
        notes.append('H20269 实时源暂不可用，已退回仓库缓存')

    idx = bd.compute_indicators(idx_raw)
    html = bd.assemble_html(idx, source_note='；'.join(notes))
    _cache.update(html=html, ts=time.time())
    return html


if __name__ == '__main__':
    print(get_dashboard_html(force=True)[:400])

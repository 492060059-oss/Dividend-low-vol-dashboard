# -*- coding: utf-8 -*-
"""看板仓库自带的行情更新脚本（只更新 H20269，不依赖主项目）

数据源：中证指数官网 API（免费、无需鉴权）
    https://www.csindex.com.cn/csindex-home/perf/index-perf
    参数 indexCode/startDate/endDate

写入：本目录 data/H20269历史数据.csv，【只追加、不改历史】，
    保证既有的历史序列可精确复现。

用法：
    python update_data.py           # 追加最新数据
    python update_data.py --check   # 只查看会追加哪些行，不写文件
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

_HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(_HERE, 'data', 'H20269历史数据.csv')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')


def fetch_json(url, headers=None, retries=3, timeout=30):
    """带重试的 GET JSON。"""
    hdrs = {'User-Agent': UA}
    if headers:
        hdrs.update(headers)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f'请求失败（已重试{retries}次）: {url} -> {last_err}')


def beijing_now():
    return datetime.now(timezone(timedelta(hours=8)))


def update(check_only=False):
    with open(CSV_PATH, encoding='utf-8-sig') as f:
        lines = f.read().splitlines()
    data_lines = [ln for ln in lines if ln.strip()]
    if len(data_lines) < 2:
        raise RuntimeError(f'{CSV_PATH} 内容异常')

    last_date_str = data_lines[-1].split(',')[0]
    last_date = datetime.strptime(last_date_str, '%Y-%m-%d')
    print(f'[H20269] 本地末行: {last_date_str}（共 {len(data_lines)-1} 个交易日）')

    start = (last_date + timedelta(days=1)).strftime('%Y%m%d')
    end = beijing_now().strftime('%Y%m%d')
    url = ('https://www.csindex.com.cn/csindex-home/perf/index-perf'
           f'?indexCode=H20269&startDate={start}&endDate={end}')
    payload = fetch_json(url, headers={'Referer': 'https://www.csindex.com.cn/'})
    rows = payload.get('data') or []
    rows.sort(key=lambda r: r['tradeDate'])
    print(f'[H20269] 官网API返回 {len(rows)} 行（{start}~{end}）')

    if not rows:
        print('[H20269] 无新数据（当日尚未发布或已是最新）')
        return last_date_str, 0

    if rows[0]['tradeDate'] <= last_date.strftime('%Y%m%d'):
        raise RuntimeError(f'API 返回了不晚于本地末行的日期 {rows[0]["tradeDate"]}，拒绝追加')

    new_lines = []
    prev_close = None
    for r in rows:
        d = datetime.strptime(r['tradeDate'], '%Y%m%d')
        close = float(r['close'])
        pct = r.get('changePct')
        if pct is None:
            pct = (close / prev_close - 1) * 100 if prev_close else None
        prev_close = close
        vol = float(r.get('tradingVol') or 0)
        parts = [d.strftime('%Y-%m-%d'), f'{close:.2f}']
        for k in ('open', 'high', 'low'):
            v = r.get(k)
            parts.append(f'{float(v):.2f}' if v is not None else '')
        parts.append(f'{vol:.1f}')
        parts.append(f'{float(pct):.2f}%' if pct is not None else '')
        new_lines.append(','.join(parts))

    if check_only:
        print(f'[H20269] --check 模式：将追加 {len(new_lines)} 行'
              f'（至 {rows[-1]["tradeDate"]}），未写入')
        return last_date_str, len(new_lines)

    with open(CSV_PATH, 'a', encoding='utf-8-sig', newline='') as f:
        if lines and lines[-1].strip():
            f.write('\n')
        f.write('\n'.join(new_lines) + '\n')
    print(f'[H20269] 已追加 {len(new_lines)} 行 -> 末行 {rows[-1]["tradeDate"]}')
    return rows[-1]['tradeDate'], len(new_lines)


def main():
    check_only = '--check' in sys.argv
    print(f'运行时间（北京时间）: {beijing_now().strftime("%Y-%m-%d %H:%M:%S")}'
          + ('  [--check 只读模式]' if check_only else ''))
    update(check_only)
    print('完成。')


if __name__ == '__main__':
    main()

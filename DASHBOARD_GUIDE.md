# 每日数据自动更新与手机看板（GitHub Actions + Pages）

> 📍 **2026-10-27 迁移说明**：看板已从主项目仓库拆出，作为独立副项目放在本目录（`../红利低波_副项目/03_在线看板/`）。行情数据仍在主项目 `../../红利低波价格走势分析程序/data/`；日后部署 Render/Pages 时，把本目录单独建成一个 git 仓库即可。下文旧路径 `scripts/dashboard/…`、`docs/index.html` 均已对应改为本目录文件。

> 2026-10-23 建立。目标：不再手动去中证指数官网下载 xlsx；手机随时查看
> H20269 / 512890 的年线乖离率、RSI、多周期均线与中期止盈信号状态。

## 一、组成部分

| 组件 | 路径 | 作用 |
|---|---|---|
| 数据更新脚本 | 主项目 `scripts/data/update_data.py` | 拉取最新数据并写入主项目 `data/`（支持 `--check` 只读模式） |
| 看板生成脚本 | 本目录 `build_dashboard.py` | 读主项目 `data/` 两个 CSV → 生成本目录 `index.html` |
| 定时任务 | `.github/workflows/update-dashboard.yml` | 每交易日 19:30 / 22:00（北京时间）自动运行并提交 |
| 看板页面 | 本目录 `index.html` | 静态快照，双击可看；在线发布需本目录单独建 git 仓库 |
| 实时渲染模块 | 本目录 `dashboard_live.py` | 现场拉数现算（不落盘），三级数据兜底 |
| Web 服务入口 | 本目录 `dashboard_app.py` + `render.yaml` | Render 免费实例部署的实时看板（见第五节） |

## 二、数据源（均免费、无需鉴权，2026-10-23 实测）

| 标的 | 来源 | 说明 |
|---|---|---|
| H20269 全收益指数 | 中证指数官网 API `csindex-home/perf/index-perf` | 参数 `indexCode/startDate/endDate`。与本地 CSV 重叠 287 天收盘价**零差异**。⚠️ 旧 autofile 路径（`H30269perf.xls`）2024-11 后已停更，勿用 |
| 512890 ETF | 东方财富 kline API（主）+ 腾讯行情 API（备份） | 前复权口径。东财单请求全量；腾讯单次上限约 640 行，脚本自动分段合并 |

### 文件写入策略（重要）

- `data/H20269历史数据.csv`：**只追加、不改历史**（保证既有回测结果可精确复现）。
- `data/512890行情数据.csv`：看板专用，每次**全量刷新**（分红除权后前复权序列整体变化，全量刷才能保持口径一致）。
- `data/512890历史数据.csv`：回测用原始文件，**保持不动**（新文件与其价格差异仅 ±0.001 舍入，但为守住"旧回测可复现"的纪律不覆盖）。
- `data/H30269perf.xlsx` / `H30269历史数据.csv`：旧手工流程，保留但看板不再使用。

## 三、本地使用

```bash
cd ../../红利低波价格走势分析程序
python scripts/data/update_data.py           # 更新数据（可挂 Windows 计划任务）
python scripts/data/update_data.py --check   # 只看数据新旧，不写文件

cd ../红利低波_副项目/03_在线看板
python build_dashboard.py                    # 重新生成本目录 index.html
```

本地直接双击打开本目录 `index.html` 也能看（图表库走 CDN，需联网）。

## 四、GitHub 部署（一次性设置）

1. 注册/登录 GitHub，新建一个仓库（Public——免费版 Pages 仅支持公开仓库；
   仓库内只有行情数据与研究文档，无隐私内容。Private 需要 Pro 账号才能开 Pages）。
2. 本地推送（在项目根目录执行）：

   ```bash
   git init -b main          # 若尚未初始化（首次提交已由本地完成则跳过）
   git remote add origin https://github.com/<你的用户名>/<仓库名>.git
   git push -u origin main
   ```

3. 仓库页面 → **Settings → Pages** → Source 选 **Deploy from a branch**，
   Branch 选 **main**、目录选 **/docs** → Save。
4. 1~2 分钟后访问 `https://<用户名>.github.io/<仓库名>/` 即为看板（手机浏览器
   可"添加到主屏幕"当 App 用）。
5. 自动更新无需任何额外配置：workflow 文件已在仓库里，定时任务自动生效；
   也可在 **Actions → Update dashboard → Run workflow** 手动触发。
   注意：仓库 Settings → Actions → General → Workflow permissions 需选
   **Read and write permissions**（默认即允许，若推送失败优先查这里）。

## 五、备选：Render.com 实时渲染部署（dashboard_app.py）

与 GitHub Pages 的"定时生成静态页"不同，Render 方案是**打开页面时实时拉数现算**
（`dashboard_app.py` + `dashboard_live.py`，均在本目录，10 分钟缓存）：

- 数据永远最新，**512890 部分盘中打开也能看到当日价格**（东财/腾讯接口盘中可用）；
- H20269 实时源为收盘数据，当日值要等中证官网收盘后发布；
- 数据链路三级兜底：中证API/东财/腾讯 → 任一失败退回仓库 CSV（页面会标注）。

**为什么仍需要一个 git 仓库**：Render 控制台建服务必须连接 GitHub/GitLab 仓库；
它唯一免 git 的通道（CLI 直传）不支持 Windows。因此仓库在这里只是"存代码的网盘"，
推送一次后日常零操作（`render.yaml` 里 `autoDeploy: false`，数据更新不触发重建）。

部署步骤：
1. 把本仓库推到 GitHub（见第四节步骤 1~2，Pages 不用开）。
2. [render.com](https://render.com) 注册（邮箱即可）→ New → **Web Service** →
   连接该 GitHub 仓库 → Render 读取 `render.yaml` 自动填好配置 → Create。
3. 等首次构建完成（约 2~3 分钟），访问 `https://<服务名>.onrender.com/`。

注意事项：
- 免费实例**闲置 15 分钟休眠**，休眠后首次访问需 30~60 秒唤醒。手机常用的话，
  可在 [uptimerobot.com](https://uptimerobot.com)（免费）加一个每 10 分钟 ping
  `https://<服务名>.onrender.com/healthz` 的监控保活；
- 国内直连 onrender.com 一般可用，速度一般；若嫌慢可回退 GitHub Pages 方案（两者共存）；
- 本地体验同款服务：`python dashboard_app.py` → http://127.0.0.1:10000 。

## 六、看板信号定义（2026-10 历史检验结论）

看板上的四个信号灯（H20269 为主，512890 同样计算但阈值仅供参照）：

| 信号 | 定义 | 历史表现（2017 年后触发统计） |
|---|---|---|
| S1 RSI6顶背离 | 收盘创20日新高，而15日内RSI6高点(≥78)回落≥8点 | 21次；其后60日最大回撤中位 -2.7%，≤-4% 概率 33% |
| S2 RSI6超买回落 | 12日内RSI6曾≥80，随后跌破60 | 39次；60日最大回撤中位 -3.6%，≤-6% 概率 33% |
| S3 跌破MA20确认 | 反弹情景下（90日内乖离率曾<0、10日内曾≥+4%）收盘跌破MA20 | 21次；60日最大回撤中位 -3.7% |
| 观察区 | 自年线下方反弹至 乖离率≥+4.5% | 19次独立事件中 61% 最终先到 +15% 卖出线 |

**核心结论**：这些信号标记的是"阶段性休整"（中位后续回撤约 3%），**不是**
可靠的中期大顶；历史上有约六成行情在 +4.5% 观察区后继续走到 +15% 卖出线。
用法应当是**停止加仓 / 分批减仓的参考**，而非全仓了结依据。触发后 5 个交易
日内亮红灯（闪烁），15 个交易日内亮黄灯。

2026-10 实战对照：10-12 乖离率上穿 +4.5% 进入观察区 → 10-15 S2 首次触发
（当日 512890 放量 2.6 倍下跌）→ 10-19 S1 顶背离 + 乖离率 +5.15% 见阶段顶
24960 → 10-20 S2 再次触发 → 10-22 S3 破 MA20 确认，三日累计 -3.0%。

## 七、维护备注

- 中证官网 API 若未来改版（返回 400/500），先查 akshare
  `index_stock_zh_csindex` 的最新实现（本项目 2026-10 参数即来自它）。
- workflow 运行日志在仓库 Actions 页；若 csindex 当日数据发布晚于 22:00，
  次日首次运行会自动补上（脚本是增量追加，不怕跳天）。
- 512890 分红除权日（通常每年 1 月）后，前复权全序列变化属正常现象。


---

2026-10-30 补充：上线五步（GitHub Pages）
=============================================

本目录已是独立 git 仓库（首次提交已完成）。看板只依赖 index.html + plotly.min.js
两个静态文件，GitHub Pages 免费托管即可，不需要 Render 也能用。

1. 浏览器登录 GitHub → 右上角 + → New repository →
   名字如 `hongli-dashboard`，选 Public，**不要**勾选任何初始化文件 → Create。
2. 新仓库页绿色 **Code** 按钮 → **SSH** 标签 → 复制整条地址。
3. 在本文件夹打开 Git Bash（右键 → Open Git Bash Here），执行：
       git remote add origin <粘贴刚复制的 SSH 地址>
       git remote -v        ← 必看核对，必须是 git@github.com:... 形式
       git push -u origin main
4. 仓库页 → Settings → Pages → Branch 选 `main` + `/ (root)` → Save。
5. 等 1~2 分钟，访问 `https://492060059-oss.github.io/<仓库名>/`。

**日常更新**：主项目 `git pull` 拿最新数据 → 本目录 `python build_dashboard.py`
→ `git add -A && git commit -m "数据更新至x月x日" && git push`，Pages 一分钟后自动刷新。

本地图形版：双击 index.html 即可（plotly.min.js 同目录离线加载）；
实时版仍可 `python dashboard_app.py`（Render 部署见下文历史章节）。

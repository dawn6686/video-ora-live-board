# 视频高光剪辑 · 半决赛（国赛）实时看板

对标 `oceanbase-live-board` 实现的**「浏览器实时直连 + GitHub Actions 定时快照双通道」**半决赛实时监控看板，内置官方复赛获奖名单中的 **77 支晋级国赛队伍**（省一 29 支 + 省二 48 支）全量信息与复赛基线成绩。

## 核心功能

1. **双源实时数据（0 延迟直连 + 静态快照兜底）**：
   - 打开网页（无论是本地双击 `index.html` 还是挂在 GitHub Pages 上）会自动向官方接口 `https://jluat-smart-app-api.yuntu.cn/third/jsphb` 发起跨域请求，实时拉取半决赛最新成绩。
   - 支持 **30秒 / 60秒 / 3分钟** 自动轮询刷新，或随时点击「🔄 立即直连刷新」。
   - 若网络离线或接口维护，自动降级读取 `data/snapshot.js` / `data/snapshot.json` 静态快照。
2. **77 支晋级队全名单对账（含潜伏对手追踪）**：
   - 整合官方复赛获奖及晋级名单 PDF（参赛编号 `CSBH_`、团队成员姓名、省一/省二等级及序号）与复赛最终成绩。
   - **🏆 半决赛实时总榜**：展示当前半决赛名次、得分、**较复赛涨跌 (`Δ 较复赛`)**、复赛得分与名次、最后提交时间、打分耗时。
   - **🕵️ 潜伏未交晋级队**：单独列出 77 支晋级队伍中尚未在半决赛出分的队伍（按复赛排名排序），清楚掌握还有多少复赛高分选手尚未亮牌。
3. **⭐ 盯住自己的队 / 重点竞争对手**：
   - 点击任意队伍行首的 `☆` 即可置顶到顶部关注面板（保存在浏览器 `localStorage`），实时计算距离 **第 1 名、前 15%（第 11 名）、前 40%（第 30 名）** 的分差。
4. **⚡ 实时出分动态与 🔮 出分时间预测**：
   - 右侧实时动态流按打分完成时间（`DFSJ_`）倒序展示最近 3h / 12h / 24h / 全部出分记录及较复赛提分幅度。
   - 自动统计半决赛全量提交的 `DFSJ_ - ZPZHTJSJ_` 评测耗时中位数与 P80 区间，预测当前提交何时出分。

## 本地使用

1. **直接打开**：双击 [`index.html`](./index.html) 即可在浏览器中使用（会自动直连官方接口刷新）。
2. **手动更新本地静态快照**：
   ```bash
   python scripts/update_snapshot.py
   ```

## 部署到 GitHub Pages（像 OceanBase 看板一样在线访问）

将本目录（`live_board/`）作为一个独立 GitHub 仓库推送到 GitHub：
1. 在 GitHub 仓库的 **Settings → Pages → Build and deployment** 中，将 **Source** 设为 **GitHub Actions**。
2. [`.github/workflows/pages.yml`](./.github/workflows/pages.yml) 会每 10 分钟自动运行 `python scripts/update_snapshot.py` 归档快照并更新 GitHub Pages，同时你打开网页时浏览器也会直接拉取官方秒级最新数据。

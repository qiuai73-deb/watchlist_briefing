# A股盘前持仓简报（GitHub Actions 云端版）

把盘前持仓简报自动化搬到 GitHub，**完全云端运行，不依赖本地电脑**。

## 功能
- 每个交易日 **08:30（北京时间）** 自动生成盘前简报
- 数据源：东方财富公开接口（公告池 / 逐股公告 / 行情 / 快讯）
- AI 生成：DeepSeek（需 key）或 GitHub Models（**免 key**）
- 输出：`briefs/YYYY-MM-DD-盘前简报.md`，并自动推送到飞书群机器人（不再生成网页）

## 快速开始
1. 新建（建议私有）仓库，提交本目录全部内容
2. （可选）配置 Secrets：
   - `LLM_API_KEY`：填 DeepSeek API Key（质量更好）
   - **不填**则用 GitHub Models 免 key 方案（需 `models: read` 权限，workflow 已默认开启）
3. 确认 `watchlist.md` 是你的自选股
4. Actions 页面点 **Run workflow** 手动跑一次验证
5. 之后每个交易日自动运行

## 自选股增减
直接编辑 `watchlist.md`，按表格格式增删一行即可，下次运行自动生效。
（进阶：可改用 Issue 触发自动改文件，见 fetch.py 注释。）

## 推送到飞书（群机器人）
简报生成后由 `notify.py` 自动推送到飞书群机器人，**不再生成网页**。

配置（仓库 **Settings → Secrets and variables → Actions → New repository secret**）：

| Secret | 说明 | 必填 |
|--------|------|------|
| `FEISHU_WEBHOOK` | 飞书群机器人 webhook 地址（`https://open.feishu.cn/open-apis/bot/v2/hook/xxxx`） | ✅ 必填 |
| `FEISHU_SECRET` | 机器人「加签」密钥（在机器人安全设置中开启加签后获得） | 可选 |

添加方式：
1. 飞书群 → 设置 → 群机器人 → 添加机器人 → 自定义机器人，拿到 **webhook 地址**
2. （可选）机器人安全设置里开启「加签」，复制 **密钥** 填到 `FEISHU_SECRET`
3. 仓库 Secrets 里新增 `FEISHU_WEBHOOK`（必填）与 `FEISHU_SECRET`（可选）
4. 之后每次运行，简报自动以富文本（`post`）形式推送到该群；内容过长会自动分多条

说明：
- `notify.py` 把简报 Markdown 转成飞书 `post` 富文本（标题加粗、表格转首列加粗行、`**加粗**` 渲染为粗体、emoji 原样保留）
- 飞书 post 消息有长度限制，超长时自动按段落切片、分多条发送
- webhook 与密钥**只**存放在仓库 Secrets，绝不写入代码或 git 历史

## 本地测试
```bash
pip install requests chinese_calendar
python fetch.py
export LLM_API_KEY=sk-xxx        # 或 export GITHUB_TOKEN=ghp_xxx
python generate.py
export FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxxx   # 必填
export FEISHU_SECRET=xxxxxxxx    # 可选（开启加签时填）
python notify.py
```

## 安全说明
- LLM 密钥**只**存放在仓库 Secrets，绝不写入代码或 git 历史
- 代码、prompt 模板、简报内容可安全提交

## 注意事项
- 东财接口在 GitHub 机房 IP 可能被限流，脚本已加 UA / 重试；如不稳定可加代理
- A股长假（春节/国庆）cron 不区分，已用 `chinese_calendar` 判断交易日，非交易日跳过生成
- 新闻源为新浪财经滚动（东财快讯/财联社接口已失效），若字段变动需同步调整 fetch.py（已在代码中标注）

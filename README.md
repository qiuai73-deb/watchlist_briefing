# A股盘前持仓简报（GitHub Actions 云端版）

把盘前持仓简报自动化搬到 GitHub，**完全云端运行，不依赖本地电脑**。

## 功能
- 每个交易日 **08:30（北京时间）** 自动生成盘前简报
- 数据源：东方财富公开接口（公告池 / 逐股公告 / 行情 / 快讯）
- AI 生成：DeepSeek（需 key）或 GitHub Models（**免 key**）
- 输出：`briefs/YYYY-MM-DD-盘前简报.md`，手机 GitHub App 可直接看

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

## 发布到网页（GitHub Pages / `*.github.io`）
简报同时生成一份 HTML 网页版，可一键托管到你的 `*.github.io` 站点：

1. 仓库 **Settings → Pages → Build and deployment → Source** 选 **`Deploy from a branch`**
2. **Branch** 选 `main`，目录选 **`/docs`**，保存
3. 几分钟后访问 `https://<你的用户名>.github.io/<仓库名>/` 即可看到索引页
   - 若仓库名就是 `<用户名>.github.io`（用户页），则访问 `https://<用户名>.github.io/`

说明：
- `generate.py` 会把简报渲染成 `docs/briefs/YYYY-MM-DD-盘前简报.html`，并自动维护 `docs/index.html` 索引页
- `docs/.nojekyll` 已自动生成，确保 HTML 原样托管、不被 Jekyll 改写
- workflow 的 commit 步骤已包含 `docs/`，无需额外配置
- 网页与仓库里的 `.md` 简报内容一致，只是多了一个浏览器可读的版本

## 本地测试
```bash
pip install requests chinese_calendar
python fetch.py
export LLM_API_KEY=sk-xxx        # 或 export GITHUB_TOKEN=ghp_xxx
python generate.py
```

## 安全说明
- LLM 密钥**只**存放在仓库 Secrets，绝不写入代码或 git 历史
- 代码、prompt 模板、简报内容可安全提交

## 注意事项
- 东财接口在 GitHub 机房 IP 可能被限流，脚本已加 UA / 重试；如不稳定可加代理
- A股长假（春节/国庆）cron 不区分，已用 `chinese_calendar` 判断交易日，非交易日跳过生成
- 新闻源为新浪财经滚动（东财快讯/财联社接口已失效），若字段变动需同步调整 fetch.py（已在代码中标注）

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘前简报 - LLM 生成层（GitHub Actions 版）

读取 context.json + templates/v3.md，调用 LLM 生成 briefs/YYYY-MM-DD-盘前简报.md。

LLM 后端（环境变量切换，密钥绝不硬编码）：
- LLM_API_KEY 存在        -> DeepSeek（api.deepseek.com，模型 deepseek-chat）
- 否则用 GITHUB_TOKEN      -> GitHub Models 免 key（models.inference.ai.azure.com，模型 gpt-4o-mini）
"""

import json
import os
import glob
import datetime
from pathlib import Path

import requests
try:
    import markdown
except ImportError:
    markdown = None

BASE = Path(__file__).resolve().parent

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
GITHUB_MODELS_URL = "https://models.inference.ai.azure.com/v1/chat/completions"

# ---- 网页版（GitHub Pages /docs）模板 ----
PAGE_STYLE = """
  body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:880px;margin:0 auto;padding:24px;line-height:1.7;color:#1a1a1a;background:#fff;}
  h1,h2,h3{line-height:1.3;}
  table{border-collapse:collapse;width:100%;margin:16px 0;font-size:14px;}
  th,td{border:1px solid #ddd;padding:8px 10px;text-align:left;}
  th{background:#f5f5f5;}
  code{background:#f4f4f4;padding:2px 4px;border-radius:3px;}
  blockquote{border-left:4px solid #ccc;margin:12px 0;padding:4px 12px;color:#555;}
  a{color:#c00;}
  .date{color:#888;font-size:13px;}
"""
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{style}</style>
</head>
<body>
{content}
<hr>
<p class="date">生成于 {date} · 仅供研究参考，不构成投资建议</p>
</body>
</html>"""

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>A股盘前持仓简报</title>
<style>{style}</style>
</head>
<body>
<h1>A股盘前持仓简报</h1>
<p>每个交易日 08:30（北京时间）自动更新 · 由 GitHub Actions 云端生成</p>
<table>
<tr><th>日期</th><th>盘前简报</th></tr>
{rows}
</table>
<p class="date">仅供研究参考，不构成投资建议</p>
</body>
</html>"""


def choose_backend():
    api_key = os.environ.get("LLM_API_KEY")
    if api_key:
        return "deepseek", DEEPSEEK_URL, api_key, "deepseek-chat"
    gh = os.environ.get("GITHUB_TOKEN")
    if gh:
        return "github", GITHUB_MODELS_URL, gh, "gpt-4o-mini"
    raise SystemExit("[ERR] 未配置 LLM_API_KEY 或 GITHUB_TOKEN，无法生成。")


def build_user_prompt(context):
    ctx_text = json.dumps(context, ensure_ascii=False, indent=2)
    return (
        "以下是结构化数据（JSON），请严格据此生成简报，不要编造数据中没有的信息：\n\n"
        f"{ctx_text}\n\n"
        "请按【生成规则】中的结构与硬性规则输出 Markdown 简报。"
    )


def call_llm(backend, url, key, model, system, user):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.5,
        "max_tokens": 4000,
    }
    r = requests.post(url, json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def render_brief_html(md, date):
    """把简报 Markdown 转成完整 HTML 页面。"""
    body = markdown.markdown(md, extensions=["tables", "fenced_code"])
    return HTML_TEMPLATE.format(title=f"盘前简报 {date}", content=body,
                                date=date, style=PAGE_STYLE)


def build_index():
    """扫描 briefs/*.md，生成 docs/index.html 索引页（按日期倒序）。"""
    files = sorted(glob.glob(str(BASE / "briefs" / "*.md")), reverse=True)
    rows = []
    for f in files:
        name = os.path.basename(f)
        date = name.replace("-盘前简报.md", "")
        rows.append(
            f'<tr><td>{date}</td>'
            f'<td><a href="briefs/{date}-盘前简报.html">{date} 盘前简报</a></td></tr>'
        )
    if not rows:
        rows.append('<tr><td colspan="2">暂无简报</td></tr>')
    html = INDEX_TEMPLATE.format(rows="\n".join(rows), style=PAGE_STYLE)
    (BASE / "docs" / "index.html").write_text(html, encoding="utf-8")
    print("[OK] 索引页已生成: docs/index.html")


def main():
    ctx_path = BASE / "context.json"
    if not ctx_path.exists():
        raise SystemExit("[ERR] 未找到 context.json，请先运行 fetch.py")
    context = json.loads(ctx_path.read_text(encoding="utf-8"))
    template = (BASE / "templates" / "v3.md").read_text(encoding="utf-8")

    backend, url, key, model = choose_backend()
    print(f"[INFO] 使用 LLM 后端: {backend} (model={model})")

    md = call_llm(backend, url, key, model, template, build_user_prompt(context))

    date = datetime.date.today().strftime("%Y-%m-%d")
    out_dir = BASE / "briefs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{date}-盘前简报.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"[OK] 简报已生成: {out_path}")

    # 同步生成网页版（GitHub Pages，发布 docs/ 目录）
    html_dir = BASE / "docs" / "briefs"
    html_dir.mkdir(parents=True, exist_ok=True)
    (BASE / "docs" / ".nojekyll").write_text("", encoding="utf-8")  # 关闭 Jekyll，原样托管 HTML
    if markdown:
        (html_dir / f"{date}-盘前简报.html").write_text(
            render_brief_html(md, date), encoding="utf-8"
        )
        build_index()
        print(f"[OK] 网页版已生成: docs/briefs/{date}-盘前简报.html")
    else:
        print("[WARN] 未安装 markdown 库，跳过网页版（请 pip install markdown）")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘前简报 - LLM 生成层（GitHub Actions 版）

读取 context.json + templates/v3.md，调用 LLM 生成 briefs/YYYY-MM-DD-盘前简报.md。
生成后由 notify.py 推送到飞书（网页版已移除）。

LLM 后端（环境变量切换，密钥绝不硬编码）：
- LLM_API_KEY 存在        -> DeepSeek（api.deepseek.com，模型 deepseek-chat）
- 否则用 GITHUB_TOKEN      -> GitHub Models 免 key（models.inference.ai.azure.com，模型 gpt-4o-mini）
"""

import json
import os
import datetime
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
GITHUB_MODELS_URL = "https://models.inference.ai.azure.com/v1/chat/completions"


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
    print("[INFO] 网页版已移除，将由 notify.py 推送到飞书。")


if __name__ == "__main__":
    main()

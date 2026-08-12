#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘前简报 - 飞书推送层（GitHub Actions 版）

读取最新 briefs/YYYY-MM-DD-盘前简报.md，转换 Markdown -> 飞书 post 富文本，
推送到飞书群机器人（自定义机器人 webhook）。

环境变量（均由 GitHub Secrets 注入，绝不硬编码）：
- FEISHU_WEBHOOK : 群机器人 webhook 地址（必填）
- FEISHU_SECRET  : 机器人加签密钥（可选；配置了则启用签名校验）

说明：
- 飞书自定义机器人 post 消息的 text 节点只支持 tag/text/(href/un_escape)，
  不支持 style 字段，携带 style 会触发 19002 报错，因此本脚本不输出 style。
- post 消息对长度有限制，超出时自动按段落切片、分多条发送。
- 若 post 仍因格式被拒（如 19002），自动降级为 text 消息重发，保证触达。
"""

import os
import re
import time
import glob
import base64
import hashlib
import hmac
import datetime
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent

# 单条消息的安全上限（序列化后的 UTF-8 字节数 / 段落数）
# 飞书 post 消息体整体上限约 30KB，这里留余量按 1.5 万字节切片。
MAX_BYTES = 15000
MAX_LINES = 40

# post 因格式被拒时的错误码，触发降级为 text 重发
FORMAT_ERROR_CODES = (19001, 19002, 19003, 19011, 19036)

UA = {"User-Agent": "Mozilla/5.0 (compatible; AStockBrief/1.0)"}


def find_latest_brief():
    files = sorted(glob.glob(str(BASE / "briefs" / "*.md")), reverse=True)
    if not files:
        raise SystemExit("[ERR] 未找到 briefs/*.md，请先运行 generate.py")
    return Path(files[0])


def parse_inline(text):
    """把行内 **加粗** 拆成文本元素列表。

    飞书自定义机器人 post 不支持 style 字段，故加粗标记仅作内容保留（去掉 **）。
    """
    parts = re.split(r"\*\*(.+?)\*\*", text)
    elems = []
    for seg in parts:
        if not seg:
            continue
        elems.append({"tag": "text", "text": seg})
    return elems or [{"tag": "text", "text": text}]


def line_to_paragraph(line):
    """单行 Markdown -> 飞书 post 的一个段落（元素列表）。返回 None 表示跳过。"""
    s = line.rstrip()
    if not s.strip():
        return None

    # 标题 # / ## / ###
    m = re.match(r"^(#{1,3})\s+(.*)$", s)
    if m:
        t = m.group(2).strip()
        return [{"tag": "text", "text": t}] if t else None

    # 表格行
    if s.lstrip().startswith("|"):
        cells = [c.strip() for c in s.strip().strip("|").split("|")]
        cells = [c for c in cells if c != ""]
        # 跳过分隔行（| --- | --- |）
        if cells and all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            return None
        if not cells:
            return None
        elems = [{"tag": "text", "text": cells[0]}]
        for c in cells[1:]:
            elems.append({"tag": "text", "text": "   " + c})
        return elems

    # 无序列表
    m = re.match(r"^[-*]\s+(.*)$", s)
    if m:
        return [{"tag": "text", "text": "• "}] + parse_inline(m.group(1))

    # 普通文本（含行内加粗）
    return parse_inline(s)


def md_to_post(md):
    """整篇 Markdown -> (title, [paragraph, ...])。"""
    title = "盘前持仓简报"
    paras = []
    for raw in md.splitlines():
        m = re.match(r"^#\s+(.*)$", raw)
        if m and title == "盘前持仓简报":
            title = m.group(1).strip()
            continue
        p = line_to_paragraph(raw)
        if p:
            paras.append(p)
    return title, paras


def paras_to_text(paras):
    """把段落列表拍平成纯文本（降级为 text 消息时用）。"""
    lines = []
    for p in paras:
        lines.append("".join(e.get("text", "") for e in p))
    return "\n".join(lines)


def chunk_paragraphs(paras):
    """把段落列表切成多条消息（受 UTF-8 字节长度 / 行数限制）。"""
    chunks, cur, cur_len, cur_lines = [], [], 0, 0
    for p in paras:
        p_len = sum(len(e.get("text", "").encode("utf-8")) for e in p) + 8
        if (cur_lines >= MAX_LINES or cur_len + p_len > MAX_BYTES) and cur:
            chunks.append(cur)
            cur, cur_len, cur_lines = [], 0, 0
        cur.append(p)
        cur_len += p_len
        cur_lines += 1
    if cur:
        chunks.append(cur)
    return chunks


def sign_url(webhook, secret):
    """飞书机器人加签：在 webhook 后追加 timestamp & sign 查询参数。"""
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(secret.encode("utf-8"),
                         string_to_sign.encode("utf-8"),
                         digestmod=hashlib.sha256).digest()
    sign = base64.b64encode(hmac_code).decode("utf-8")
    sep = "&" if "?" in webhook else "?"
    return f"{webhook}{sep}timestamp={timestamp}&sign={sign}"


def _post_json(webhook, payload):
    r = requests.post(webhook, json=payload, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def send_chunk(webhook, title, chunk, idx, total):
    """优先发 post 富文本；若被格式类错误拒绝（如 19002），降级为 text 纯文本重发。"""
    t = title if idx == 1 else f"{title}（{idx}/{total}）"
    post_payload = {
        "msg_type": "post",
        "content": {"post": {"zh_cn": {"title": t, "content": chunk}}},
    }
    resp = _post_json(webhook, post_payload)
    if resp.get("code", 0) == 0:
        return
    code = resp.get("code")
    if code in FORMAT_ERROR_CODES:
        print(f"[WARN] post 被拒(code={code})，降级为 text 重发")
        text_payload = {
            "msg_type": "text",
            "content": {"text": f"{t}\n\n{paras_to_text(chunk)}"},
        }
        resp2 = _post_json(webhook, text_payload)
        if resp2.get("code", 0) != 0:
            raise SystemExit(f"[ERR] 飞书(text)返回错误: {resp2}")
        return
    raise SystemExit(f"[ERR] 飞书返回错误: {resp}")


def main():
    webhook = os.environ.get("FEISHU_WEBHOOK")
    if not webhook:
        raise SystemExit("[ERR] 未配置 FEISHU_WEBHOOK，无法推送飞书。请在仓库 Secrets 中配置。")
    secret = os.environ.get("FEISHU_SECRET")
    if secret:
        webhook = sign_url(webhook, secret)
        print("[INFO] 已启用飞书加签校验。")

    brief = find_latest_brief()
    print(f"[INFO] 读取简报: {brief}")
    md = brief.read_text(encoding="utf-8")

    title, paras = md_to_post(md)
    if not paras:
        raise SystemExit("[ERR] 简报内容为空，未生成任何段落。")

    chunks = chunk_paragraphs(paras)
    print(f"[INFO] 拆分为 {len(chunks)} 条飞书消息发送（共 {len(paras)} 段）")

    date = datetime.date.today().strftime("%Y-%m-%d")
    for i, chunk in enumerate(chunks, 1):
        send_chunk(webhook, title, chunk, i, len(chunks))
        print(f"[OK] 第 {i}/{len(chunks)} 条已发送（{len(chunk)} 段）")
        time.sleep(0.5)  # 避免群机器人频率限制

    print(f"[OK] 飞书推送完成：{date} 盘前简报")


if __name__ == "__main__":
    main()

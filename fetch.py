#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘前简报 - 数据抓取层（GitHub Actions 版）

抓取：东财全A公告池、逐股公告、行情、快讯（宏观/行业/个股）。
输出：context.json（供 generate.py 使用）。

说明：
- 所有请求走东方财富公开 HTTP 接口，无需鉴权。
- 新闻用东财快讯流 + 域名黑名单过滤；若接口字段变动，调整 fetch_kuaixun 内的解析即可。
- 可选进阶：监听 GitHub Issue（label=add-stock）自动改 watchlist.md，
  在 workflow 中加 `issues` 触发器并解析 issue 正文即可。
"""
import json
import re
import sys
import time
import datetime
from pathlib import Path

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}

# 自媒体黑名单（用于过滤任何外链/来源）
BLOCKED_DOMAINS = [
    "baijiahao.baidu.com", "sohu.com", "163.com", "zhihu.com",
    "xueqiu.com", "caifuhao.eastmoney.com", "guba.sina.com.cn",
    "guba.eastmoney.com", "toutiao.com",
]

BASE = Path(__file__).resolve().parent


def _get(url, params=None, timeout=15, retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r
        except Exception as e:
            if i == retries - 1:
                print(f"[WARN] 请求失败 {url}: {e}", file=sys.stderr)
        time.sleep(2 + i)
    return None


def market_prefix(code: str) -> str:
    """沪市(1) / 深市(0)"""
    return "1" if code[0] in ("6", "9") else "0"


def parse_watchlist(path: Path):
    stocks = []
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        m = re.match(
            r"\|\s*(\d+)\s*\|\s*(\d{6})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
            line,
        )
        if m:
            stocks.append({
                "idx": m.group(1), "code": m.group(2), "name": m.group(3).strip(),
                "industry": m.group(4).strip(), "tags": m.group(5).strip(),
            })
    return stocks


def fetch_ann_pool(n=30):
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {"page_size": n, "page_index": 1, "ann_type": "A",
              "client_source": "web", "f_node": 0, "s_node": 0}
    r = _get(url, params)
    if not r:
        return []
    try:
        items = r.json().get("data", {}).get("list", [])
    except Exception:
        return []
    out = []
    for it in items[:n]:
        codes = ",".join(f"{c.get('short_name','')}({c.get('stock_code','')})"
                         for c in it.get("codes", [])[:2])
        out.append({"date": str(it.get("notice_date", ""))[:10],
                    "codes": codes, "title": str(it.get("title", "")),
                    "url": it.get("url", "")})
    return out


def fetch_stock_ann(code, n=15):
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {"page_size": n, "page_index": 1, "ann_type": "A",
              "client_source": "web", "stock_list": code}
    r = _get(url, params)
    if not r:
        return []
    try:
        items = r.json().get("data", {}).get("list", [])
    except Exception:
        return []
    return [{"date": str(it.get("notice_date", ""))[:10],
             "title": str(it.get("title", "")), "url": it.get("url", "")}
            for it in items[:n]]


def _fetch_quote_push2(code):
    secid = f"{market_prefix(code)}.{code}"
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {"secid": secid, "fields": "f57,f58,f43,f60,f170,f169,f47,f48,f116,f162,f167,f168"}
    r = _get(url, params)
    if not r:
        return {}
    try:
        d = r.json().get("data", {})
    except Exception:
        return {}

    def num(k):
        v = d.get(k)
        try:
            return float(v) if v not in (None, "-", "") else None
        except Exception:
            return None

    return {
        "code": code, "name": d.get("f58"),
        "price": num("f43"), "prev_close": num("f60"), "pct": num("f170"),
        "amount": num("f48"), "turnover": num("f168"), "mktcap": num("f116"),
    }


def _fetch_quote_gtimg(code):
    """腾讯行情回退源（对海外 IP 更友好）。

    注意：不能带 Referer，否则东财会返回 UTF-8 而非 GBK，导致解析错位（价格×100）。
    """
    prefix = "sh" if code[0] in ("6", "9") else "sz"
    url = f"https://qt.gtimg.cn/q={prefix}{code}"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        r.encoding = "gbk"
        m = re.search(r'="([^"]+)"', r.text)
        if not m:
            return {}
        parts = m.group(1).split("~")
        name = parts[1]
        price = float(parts[3])
        prev = float(parts[4])
        pct = round((price - prev) / prev * 100, 2) if prev else None
        return {"code": code, "name": name, "price": price, "prev_close": prev,
                "pct": pct, "amount": None, "turnover": None, "mktcap": None}
    except Exception:
        return {}


def fetch_quote(code):
    # 腾讯 gtimg 主源：对海外 IP 稳定、返回 GBK，已验证价格准确。
    # （东财 push2 在海外 IP 易断连/偶发返回异常数据，故不优先使用；
    #  _fetch_quote_push2 保留，国内部署可改回优先。）
    return _fetch_quote_gtimg(code)


def fetch_news(n_pages=3):
    """新浪财经滚动新闻（原东财快讯接口已失效 404）。
    返回 {time, title, intro, src, url} 列表；下游用域名黑名单过滤自媒体。
    """
    items = []
    headers = {"User-Agent": UA, "Referer": "https://finance.sina.com.cn"}
    for p in range(1, n_pages + 1):
        try:
            r = requests.get(
                "https://feed.mix.sina.com.cn/api/roll/get",
                params={"pageid": "153", "lid": "2509", "num": 20, "page": p},
                headers=headers, timeout=15,
            )
            data = r.json().get("result", {}).get("data", []) or []
            for it in data:
                ctime = it.get("ctime")
                ts = datetime.datetime.fromtimestamp(int(ctime)).strftime("%Y-%m-%d %H:%M") if ctime else ""
                intro = re.sub(r"<[^>]+>", "", str(it.get("intro") or it.get("summary") or ""))
                items.append({
                    "time": ts,
                    "title": it.get("title", ""),
                    "intro": intro,
                    "src": it.get("media_name", "sina.com.cn"),
                    "url": it.get("url", ""),
                })
        except Exception:
            pass
        time.sleep(1)
    return items


def blocked(url_or_domain: str) -> bool:
    return any(bd in (url_or_domain or "") for bd in BLOCKED_DOMAINS)


def extract_relevant_news(news, stocks, keywords):
    out = []
    names = [s["name"] for s in stocks]
    for it in news:
        c = f"{it.get('title', '')} {it.get('intro', '')}"
        if blocked(it.get("src", "")):
            continue
        hit = [nm for nm in names if nm in c] + [kw for kw in keywords if kw in c]
        if hit:
            out.append({"time": it.get("time", ""), "content": c[:200],
                        "src": it.get("src", ""), "hit": hit[:3]})
    seen, uniq = set(), []
    for o in out:
        k = o["content"][:40]
        if k not in seen:
            seen.add(k)
            uniq.append(o)
    return uniq[:40]


def is_trading_day(dt=None):
    try:
        from chinese_calendar import is_workday
        dt = dt or datetime.date.today()
        return is_workday(dt)
    except Exception:
        wd = (dt or datetime.date.today()).weekday()
        return wd < 5


def main():
    wl = parse_watchlist(BASE / "watchlist.md")
    print(f"[INFO] 解析自选股 {len(wl)} 支: {[s['name'] for s in wl]}")

    trading = is_trading_day()
    if not trading:
        print("[INFO] 今日非交易日（周末/节假日），周末梳理版生成。")

    ann_pool = fetch_ann_pool(30)
    stocks_data = []
    for s in wl:
        print(f"[INFO] 抓取 {s['name']}({s['code']}) ...")
        stocks_data.append({
            "code": s["code"], "name": s["name"],
            "industry": s["industry"], "tags": s["tags"],
            "announcements": fetch_stock_ann(s["code"]),
            "quote": fetch_quote(s["code"]),
        })
        time.sleep(1)

    news = fetch_news()
    sector_kw = ["半导体", "光通信", "CPO", "光纤", "电网", "储能", "充电桩",
                 "特高压", "碳化硅", "封测", "存储芯片", "MCU", "AI算力", "数据中心"]
    macro_kw = ["美股", "纳斯达克", "标普", "道琼斯", "中概", "央行", "降准", "降息",
                "美联储", "CPI", "美债", "黄金", "原油", "A股", "收评", "复盘"]
    news_sector = extract_relevant_news(news, wl, sector_kw)
    news_macro = extract_relevant_news(news, wl, macro_kw)

    context = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "is_trading_day": trading,
        "ann_pool_top": ann_pool[:30],
        "stocks": stocks_data,
        "news_macro": news_macro,
        "news_sector": news_sector,
    }
    out = BASE / "context.json"
    out.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 写入 {out} (宏观新闻 {len(news_macro)} 条, 行业新闻 {len(news_sector)} 条)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
线索采集管道 — 可跑演示版

设计目标（对应客户需求）：抓 → 结构化 → 打意向标签 → 输出可导入企微的 CSV

用法:
    python3 leadpipe.py --source hn --limit 30 --out leads.csv

设计原则:
  1. 配置驱动：换站只改 config，不改代码
  2. 失败可见：抓不到就报错，绝不静默返回空表
  3. 可追溯：每条线索带来源 URL 和抓取时间
  4. 幂等：重复跑不会产生重复行（按 unique_key 去重）
"""
import argparse, csv, json, sys, time, hashlib
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

UA = "LeadPipe/0.1 (contact: h2697930443@gmail.com)"

SOURCES = {
    # 演示源：Hacker News 公开 API（无需登录、稳定、可复现）
    "hn": {
        "list_url": "https://hacker-news.firebaseio.com/v0/topstories.json",
        "item_url": "https://hacker-news.firebaseio.com/v0/item/{id}.json",
        "site_url": "https://news.ycombinator.com/item?id={id}",
    },
    # 真实场景接入示例（装修垂类）：把这里换成客户的平台即可
    # 结构完全一样：一个列表接口 + 一个详情接口
}


def fetch(url, retries=3, base_delay=1.0):
    last = None
    for i in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urlopen(req, timeout=15) as r:
                return r.read()
        except (URLError, HTTPError) as e:
            last = e
            time.sleep(base_delay * (2 ** i))
    raise RuntimeError(f"fetch failed after {retries}: {url} -> {last}")


def score_intent(text):
    """意向分级。规则简单但可解释——客户能自己看懂为什么这条是 A。"""
    t = (text or "").lower()
    signals = []
    score = 0
    if any(k in t for k in ["hiring", "hire", "we're looking", "seeking", "recruiting"]):
        signals.append("招聘信号"); score += 3
    if any(k in t for k in ["customer", "client", "lead", "sales", "growth"]):
        signals.append("销售/获客相关"); score += 2
    if any(k in t for k in ["ai", "automation", "scrape", "crawler", "data"]):
        signals.append("技术需求相关"); score += 2
    if any(k in t for k in ["budget", "$", "paid", "contract"]):
        signals.append("预算信号"); score += 2
    if score >= 5:
        return "A", score, signals
    if score >= 3:
        return "B", score, signals
    return "C", score, signals


def run(source, limit, out_path):
    cfg = SOURCES.get(source)
    if not cfg:
        raise SystemExit(f"unknown source: {source}")

    ids = json.loads(fetch(cfg["list_url"]))[:limit]
    if not ids:
        raise SystemExit("列表接口返回空 —— 这是异常，不是'没有数据'")

    rows, errors = [], []
    for i, item_id in enumerate(ids, 1):
        try:
            raw = fetch(cfg["item_url"].format(id=item_id))
            item = json.loads(raw)
            if not item or item.get("deleted") or item.get("dead"):
                errors.append((item_id, "deleted/dead"))
                continue
            title = item.get("title") or ""
            text = item.get("text") or ""
            grade, score, signals = score_intent(title + " " + text)
            rows.append({
                "unique_key": hashlib.md5(f"{source}:{item_id}".encode()).hexdigest()[:16],
                "source": source,
                "source_url": cfg["site_url"].format(id=item_id),
                "title": title.replace("\n", " ").strip(),
                "author": item.get("by", ""),
                "score": item.get("score", 0),
                "intent_grade": grade,
                "intent_score": score,
                "signals": "|".join(signals),
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
        except Exception as e:
            errors.append((item_id, str(e)[:60]))
        if i % 10 == 0:
            print(f"  ... {i}/{len(ids)}", file=sys.stderr)

    if not rows:
        raise SystemExit(f"抓到 0 条（{len(errors)} 条失败）—— 按设计这属于失败，不输出空表")

    # 幂等：按 unique_key 去重
    seen, deduped = set(), []
    for r in rows:
        if r["unique_key"] in seen:
            continue
        seen.add(r["unique_key"])
        deduped.append(r)
    deduped.sort(key=lambda r: (-r["intent_score"], -r["score"]))

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(deduped[0].keys()))
        w.writeheader()
        w.writerows(deduped)

    a = sum(1 for r in deduped if r["intent_grade"] == "A")
    b = sum(1 for r in deduped if r["intent_grade"] == "B")
    c = len(deduped) - a - b
    print(f"\n输出: {out_path}")
    print(f"总数 {len(deduped)} | A {a} | B {b} | C {c} | 失败 {len(errors)}")
    return deduped


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="hn")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--out", default="leads.csv")
    args = ap.parse_args()
    run(args.source, args.limit, args.out)

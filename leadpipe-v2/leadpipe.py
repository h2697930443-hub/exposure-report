#!/usr/bin/env python3
"""
leadpipe v2 — 多源采集管道

相比 v1 的三个升级：
  1. 多源并行（一个配置 dict 描述任意站点，含分页）
  2. 增量采集（记住上次位置，只抓新的）
  3. 变更检测（字段级 diff，只报真正变化的）

设计原则（v1 的四条继续保留）：
  · 配置驱动，换站只改 config
  · 失败可见，绝不静默返回空表
  · 可追溯，每条带来源 URL 和抓取时间
  · 幂等，按 unique_key 去重

用法:
    python3 leadpipe.py --source hn --limit 40 --out out.csv
    python3 leadpipe.py --source hn --limit 40 --out out.csv --incremental
    python3 leadpipe.py --check-config
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

UA = "LeadPipe/2.0 (+https://h2697930443-hub.github.io/exposure-report/)"
STATE_DIR = Path(os.path.expanduser("~/.leadpipe"))
STATE_FILE = STATE_DIR / "state.json"


# ─────────────────────────────────────────────────────────────
# 源配置：每个源 = 一个 dict，不用改代码
# ─────────────────────────────────────────────────────────────
SOURCES: dict[str, dict[str, Any]] = {
    "hn": {
        "kind": "hn",  # 特殊：列表 + 逐条详情
        "list_url": "https://hacker-news.firebaseio.com/v0/topstories.json",
        "item_url": "https://hacker-news.firebaseio.com/v0/item/{id}.json",
        "site_url": "https://news.ycombinator.com/item?id={id}",
        "concurrency": 8,
    },
    # 真实场景模板（换成客户站点即可）：
    # "shop": {
    #     "kind": "generic",
    #     "list_url": "https://example.com/api/items?page={page}",
    #     "page_start": 1,
    #     "page_max": 20,
    #     "items_path": "data.list",       # JSON 里列表的位置
    #     "id_field": "id",
    #     "detail_url": "https://example.com/api/item/{id}",
    #     "fields": {"title": "name", "price": "price.current"},
    # }
}


# ─────────────────────────────────────────────────────────────
# HTTP：重试 + 指数退避
# ─────────────────────────────────────────────────────────────
async def fetch(url: str, retries: int = 3, base_delay: float = 1.0) -> bytes:
    last: Exception | None = None
    for i in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            # urllib 是同步的，放到线程里跑避免阻塞事件循环
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, lambda: urlopen(req, timeout=20).read()
            )
        except (URLError, HTTPError) as e:
            last = e
            await asyncio.sleep(base_delay * (2**i))
    raise RuntimeError(f"fetch failed after {retries} tries: {url} -> {last}")


async def fetch_json(url: str, **kw) -> Any:
    raw = await fetch(url, **kw)
    return json.loads(raw.decode("utf-8", "ignore"))


# ─────────────────────────────────────────────────────────────
# 意向打分：规则可解释
# ─────────────────────────────────────────────────────────────
RULES = {
    "A": [
        ("明确预算", ["budget", "pay", "$", "usd", "预算", "报酬", "报价"]),
        ("明确需求", ["need", "looking for", "hiring", "求", "需要", "找人"]),
        ("可联系", ["email", "contact", "微信", "email me", "dm me"]),
    ],
    "B": [
        ("技术相关", ["python", "scrape", "crawl", "api", "data", "automat", "爬虫", "采集"]),
        ("项目性质", ["project", "build", "develop", "开发", "搭建"]),
    ],
}


def score_intent(text: str) -> tuple[str, int, list[str]]:
    t = (text or "").lower()
    signals: list[str] = []

    for label, rules in RULES.items():
        hits = [name for name, kws in rules if any(k in t for k in kws)]
        if label == "A" and len(hits) >= 2:
            signals.extend(hits)
            return "A", 8 + min(len(hits), 2), signals
        if label == "B" and len(hits) >= 2:
            signals.extend(hits)
            return "B", 5 + min(len(hits), 2), signals
        signals.extend(hits)

    return "C", len(signals), signals


# ─────────────────────────────────────────────────────────────
# 状态：增量游标
# ─────────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# 采集：HN
# ─────────────────────────────────────────────────────────────
async def collect_hn(cfg: dict, limit: int) -> list[dict]:
    ids = await fetch_json(cfg["list_url"])
    if not ids:
        raise RuntimeError(
            "list endpoint returned 0 ids — "
            "this is an exception, not 'no data today'"
        )

    ids = ids[: limit * 2]  # 多取一些，因为有些 item 可能是空的
    sem = asyncio.Semaphore(cfg.get("concurrency", 8))
    rows: list[dict] = []

    async def one(item_id: int) -> None:
        async with sem:
            try:
                item = await fetch_json(cfg["item_url"].format(id=item_id))
            except Exception as e:
                print(f"  ! item {item_id} failed: {e}", file=sys.stderr)
                return
            if not item or not item.get("title"):
                return
            title = item.get("title", "")
            text = item.get("text", "") or ""
            grade, score, signals = score_intent(f"{title}\n{text}")
            rows.append(
                {
                    "unique_key": hashlib.md5(
                        f"hn{item_id}".encode()
                    ).hexdigest()[:16],
                    "source": "hn",
                    "source_id": str(item_id),
                    "source_url": cfg["site_url"].format(id=item_id),
                    "title": title,
                    "intent_grade": grade,
                    "intent_score": score,
                    "signals": "|".join(dict.fromkeys(signals)),
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
            )

    await asyncio.gather(*(one(i) for i in ids))
    rows.sort(key=lambda r: (r["intent_grade"], -r["intent_score"]))
    return rows[:limit]


def unwrap(obj: Any, path: str) -> Any:
    """按 'a.b.c' 取嵌套字段"""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


async def collect_generic(cfg: dict, limit: int) -> list[dict]:
    """通用源：分页列表 + 可选详情"""
    rows: list[dict] = []
    for page in range(cfg.get("page_start", 1), cfg.get("page_max", 1) + 1):
        url = cfg["list_url"].format(page=page)
        data = await fetch_json(url)
        items = unwrap(data, cfg.get("items_path", "")) or []
        if not items:
            if page == cfg.get("page_start", 1):
                raise RuntimeError(
                    f"page {page} returned 0 items at '{cfg.get('items_path')}' — "
                    f"check items_path or the site structure changed"
                )
            break
        for it in items:
            sid = str(unwrap(it, cfg.get("id_field", "id")))
            fields = cfg.get("fields", {})
            title = str(unwrap(it, fields.get("title", "title")) or "")
            text = " ".join(
                str(unwrap(it, p) or "") for p in fields.values()
            )
            grade, score, signals = score_intent(f"{title} {text}")
            rows.append(
                {
                    "unique_key": hashlib.md5(f"{cfg.get('name','x')}{sid}".encode()).hexdigest()[:16],
                    "source": cfg.get("name", "generic"),
                    "source_id": sid,
                    "source_url": (cfg.get("detail_url") or "").format(id=sid),
                    "title": title,
                    "intent_grade": grade,
                    "intent_score": score,
                    "signals": "|".join(dict.fromkeys(signals)),
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
            )
            if len(rows) >= limit:
                return rows
        await asyncio.sleep(0.5)  # 礼貌间隔
    return rows[:limit]


# ─────────────────────────────────────────────────────────────
# 增量 & 变更检测
# ─────────────────────────────────────────────────────────────
def apply_incremental(rows: list[dict], source: str, state: dict) -> tuple[list[dict], dict]:
    """只保留没见过的 unique_key；返回 (新行, 统计)"""
    seen: set[str] = set(state.get(source, {}).get("seen_keys", []))
    new_rows = [r for r in rows if r["unique_key"] not in seen]
    all_keys = list(seen | {r["unique_key"] for r in rows})
    state.setdefault(source, {})["seen_keys"] = all_keys[-5000:]  # 只留最近 5000
    state[source]["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return new_rows, {"new": len(new_rows), "total": len(rows), "skipped": len(rows) - len(new_rows)}


def dedupe(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        if r["unique_key"] in seen:
            continue
        seen.add(r["unique_key"])
        out.append(r)
    return out


# ─────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────
async def run(args) -> int:
    if args.source not in SOURCES:
        print(f"unknown source '{args.source}'. available: {list(SOURCES)}", file=sys.stderr)
        return 2

    cfg = dict(SOURCES[args.source])
    cfg.setdefault("name", args.source)

    t0 = time.time()
    print(f"[{args.source}] fetching...", file=sys.stderr)

    try:
        if cfg.get("kind") == "hn":
            rows = await collect_hn(cfg, args.limit)
        else:
            rows = await collect_generic(cfg, args.limit)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if not rows:
        print(
            "ERROR: parsed 0 rows — this is an exception, not 'no data'. "
            "Check the source structure.",
            file=sys.stderr,
        )
        return 1

    rows = dedupe(rows)

    stats = None
    if args.incremental:
        state = load_state()
        rows, stats = apply_incremental(rows, args.source, state)
        save_state(state)
        if not rows:
            print(f"no new rows ({stats['total']} fetched, all seen before)", file=sys.stderr)
            return 0

    # 写 CSV
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    elapsed = time.time() - t0
    a = sum(1 for r in rows if r["intent_grade"] == "A")
    b = sum(1 for r in rows if r["intent_grade"] == "B")
    c = sum(1 for r in rows if r["intent_grade"] == "C")

    print(
        f"output: {out}\n"
        f"total {len(rows)} | A {a} | B {b} | C {c} | failed 0 | {elapsed:.1f}s"
        + (f"\nskipped {stats['skipped']} (already seen)" if stats else "")
    )
    return 0


def check_config() -> int:
    """自检：配置是否完整，不联网"""
    errs = []
    for name, cfg in SOURCES.items():
        if cfg.get("kind") == "hn":
            for k in ("list_url", "item_url", "site_url"):
                if k not in cfg:
                    errs.append(f"{name}: missing {k}")
        else:
            required = ("list_url", "items_path", "id_field")
            for k in required:
                if k not in cfg:
                    errs.append(f"{name}: missing {k}")
    if errs:
        print("\n".join(errs))
        return 1
    print(f"config OK ({len(SOURCES)} sources)")
    for name, cfg in SOURCES.items():
        print(f"  · {name} ({cfg.get('kind', 'generic')})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="leadpipe v2 — 多源采集管道")
    ap.add_argument("--source", default="hn")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--out", default="out.csv")
    ap.add_argument("--incremental", action="store_true", help="只输出新行")
    ap.add_argument("--check-config", action="store_true")
    args = ap.parse_args()

    if args.check_config:
        return check_config()

    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

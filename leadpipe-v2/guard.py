#!/usr/bin/env python3
"""
guard.py — 采集健康检查

这是 leadpipe 最重要的一个模块。
解决的问题：爬虫静默失败（返回空表但 exit 0），客户三周后才发现数据全丢。

三个检查：
  1. 结果为空？→ 异常
  2. 结果量比上次骤降 50%+？→ 异常（可能是解析部分挂了）
  3. 字段完整率低于阈值？→ 异常（可能是选择器变了）

用法:
    python3 guard.py --csv out.csv
    python3 guard.py --csv out.csv --baseline 100 --min-rate 0.8
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(os.path.expanduser("~/.leadpipe/guard.json"))


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def check(csv_path: Path, baseline: int | None, min_rate: float) -> tuple[bool, list[str]]:
    problems: list[str] = []

    if not csv_path.exists():
        return False, [f"CSV 不存在：{csv_path}"]

    with csv_path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    n = len(rows)

    # 检查 1：空表
    if n == 0:
        problems.append(
            "结果为 0 行 —— 这是异常，不是「今天没数据」"
        )
        return False, problems

    # 检查 2：环比骤降
    state = load_state()
    key = str(csv_path.resolve())
    prev = state.get(key, {}).get("last_count")
    if baseline is not None:
        prev = baseline
    if prev and n < prev * 0.5:
        problems.append(
            f"条数骤降：上次 {prev} 行 → 本次 {n} 行（降幅 {100*(1-n/prev):.0f}%）"
            "—— 可能是解析部分挂了"
        )

    # 检查 3：字段完整率
    if rows:
        fields = list(rows[0].keys())
        for fld in fields:
            if fld in ("unique_key", "source", "fetched_at"):
                continue  # 系统字段不计
            filled = sum(1 for r in rows if (r.get(fld) or "").strip())
            rate = filled / n
            if rate < min_rate:
                problems.append(
                    f"字段「{fld}」完整率仅 {rate:.0%}（阈值 {min_rate:.0%}）"
                    "—— 可能是选择器变了或字段缺失"
                )

    state[key] = {
        "last_count": n,
        "last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "problems": len(problems),
    }
    save_state(state)

    return len(problems) == 0, problems


def main() -> int:
    ap = argparse.ArgumentParser(description="采集健康检查")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--baseline", type=int, default=None, help="基准条数")
    ap.add_argument("--min-rate", type=float, default=0.8, help="字段最低完整率")
    ap.add_argument("--quiet", action="store_true", help="只在有问题时输出")
    args = ap.parse_args()

    ok, problems = check(Path(args.csv), args.baseline, args.min_rate)

    if ok:
        if not args.quiet:
            print(f"健康：{args.csv} 检查通过")
        return 0

    print(f"异常：{args.csv}", file=sys.stderr)
    for p in problems:
        print(f"  · {p}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

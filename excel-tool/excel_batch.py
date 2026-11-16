#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Excel 批量处理工具箱

四个功能，都是最常见、最费时间的活：
  1. 合并  — 把一个文件夹里所有 Excel 合成一张表
  2. 去重  — 按指定列去重，保留第一条
  3. 拆分  — 按某列拆成多个文件
  4. 对比  — 两个表找出差异行

用法（命令行）：
    python3 excel_batch.py merge  输入文件夹 输出.xlsx
    python3 excel_batch.py dedupe 输入.xlsx 输出.xlsx --key 订单号
    python3 excel_batch.py split  输入.xlsx 输出文件夹 --by 部门
    python3 excel_batch.py diff   表A.xlsx 表B.xlsx 差异.xlsx --key 订单号

依赖：pandas openpyxl
"""
import sys
import os
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("需要先安装 pandas：pip install pandas openpyxl")
    sys.exit(1)


def _log(msg):
    print(msg, flush=True)


def cmd_merge(folder: str, out: str) -> int:
    """合并文件夹里所有 Excel"""
    p = Path(folder)
    if not p.exists():
        print(f"文件夹不存在：{folder}")
        return 1

    files = sorted([f for f in p.iterdir()
                    if f.suffix.lower() in (".xlsx", ".xls", ".xlsm")
                    and not f.name.startswith("~$")])

    if not files:
        print(f"文件夹里没有 Excel 文件：{folder}")
        return 1

    _log(f"找到 {len(files)} 个文件")
    frames = []
    failed = []

    for f in files:
        try:
            df = pd.read_excel(f)
            if df.empty:
                _log(f"  跳过空表：{f.name}")
                continue
            df["__来源文件__"] = f.name
            frames.append(df)
            _log(f"  ✓ {f.name}  {len(df)} 行")
        except Exception as e:
            failed.append((f.name, str(e)))
            _log(f"  ✗ {f.name}  读取失败：{e}")

    if not frames:
        print("所有文件都没读到数据——这是异常，不是「没数据」")
        return 1

    result = pd.concat(frames, ignore_index=True)
    result.to_excel(out, index=False)

    _log(f"\n合并完成：{len(result)} 行 × {len(result.columns)} 列")
    _log(f"输出：{out}")
    if failed:
        _log(f"\n有 {len(failed)} 个文件读取失败：")
        for name, err in failed:
            _log(f"  · {name}：{err}")
    return 0


def cmd_dedupe(inp: str, out: str, key: str | None) -> int:
    """按列去重"""
    df = pd.read_excel(inp)
    before = len(df)

    if key:
        if key not in df.columns:
            print(f"找不到列「{key}」，现有列：{list(df.columns)}")
            return 1
        df = df.drop_duplicates(subset=[key], keep="first")
    else:
        df = df.drop_duplicates(keep="first")

    after = len(df)
    df.to_excel(out, index=False)

    _log(f"去重完成：{before} 行 → {after} 行（删除 {before-after} 行）")
    _log(f"输出：{out}")
    return 0


def cmd_split(inp: str, outdir: str, by: str) -> int:
    """按某列拆分成多个文件"""
    df = pd.read_excel(inp)

    if by not in df.columns:
        print(f"找不到列「{by}」，现有列：{list(df.columns)}")
        return 1

    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    groups = df.groupby(by)
    n = 0
    for name, group in groups:
        safe = str(name).replace("/", "_").replace("\\", "_")[:40]
        fpath = out / f"{safe}.xlsx"
        group.to_excel(fpath, index=False)
        _log(f"  ✓ {fpath.name}  {len(group)} 行")
        n += 1

    _log(f"\n拆分完成：{n} 个文件 → {outdir}")
    return 0


def cmd_diff(a: str, b: str, out: str, key: str | None) -> int:
    """两个表找差异"""
    df_a = pd.read_excel(a)
    df_b = pd.read_excel(b)

    if key:
        if key not in df_a.columns or key not in df_b.columns:
            print(f"两边都要有列「{key}」")
            return 1
        set_a = set(df_a[key].astype(str))
        set_b = set(df_b[key].astype(str))

        only_a = df_a[~df_a[key].astype(str).isin(set_b)]
        only_b = df_b[~df_b[key].astype(str).isin(set_a)]

        with pd.ExcelWriter(out) as w:
            only_a.to_excel(w, sheet_name="只在A表", index=False)
            only_b.to_excel(w, sheet_name="只在B表", index=False)

        _log(f"对比完成：")
        _log(f"  只在 A 表：{len(only_a)} 行")
        _log(f"  只在 B 表：{len(only_b)} 行")
        _log(f"输出：{out}")
    else:
        # 无 key 时按整行对比
        a_rows = set(map(tuple, df_a.astype(str).values))
        b_rows = set(map(tuple, df_b.astype(str).values))
        only_a = [r for r in df_a.astype(str).values if tuple(r) not in b_rows]
        only_b = [r for r in df_b.astype(str).values if tuple(r) not in a_rows]

        pd.DataFrame(only_a, columns=df_a.columns).to_excel(
            out.replace(".xlsx", "_A独有.xlsx"), index=False)
        pd.DataFrame(only_b, columns=df_b.columns).to_excel(
            out.replace(".xlsx", "_B独有.xlsx"), index=False)

        _log(f"对比完成：A 独有 {len(only_a)} 行，B 独有 {len(only_b)} 行")

    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]

    if cmd == "merge":
        if len(sys.argv) < 4:
            print("用法：python3 excel_batch.py merge 输入文件夹 输出.xlsx")
            return 1
        return cmd_merge(sys.argv[2], sys.argv[3])

    if cmd == "dedupe":
        if len(sys.argv) < 4:
            print("用法：python3 excel_batch.py dedupe 输入.xlsx 输出.xlsx [--key 列名]")
            return 1
        key = None
        if "--key" in sys.argv:
            key = sys.argv[sys.argv.index("--key") + 1]
        return cmd_dedupe(sys.argv[2], sys.argv[3], key)

    if cmd == "split":
        if len(sys.argv) < 5:
            print("用法：python3 excel_batch.py split 输入.xlsx 输出文件夹 --by 列名")
            return 1
        by = sys.argv[sys.argv.index("--by") + 1] if "--by" in sys.argv else None
        if not by:
            print("需要 --by 指定列名")
            return 1
        return cmd_split(sys.argv[2], sys.argv[3], by)

    if cmd == "diff":
        if len(sys.argv) < 5:
            print("用法：python3 excel_batch.py diff A.xlsx B.xlsx 输出.xlsx [--key 列名]")
            return 1
        key = sys.argv[sys.argv.index("--key") + 1] if "--key" in sys.argv else None
        return cmd_diff(sys.argv[2], sys.argv[3], sys.argv[4], key)

    print(f"未知命令：{cmd}")
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())

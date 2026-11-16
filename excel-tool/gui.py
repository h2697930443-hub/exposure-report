#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Excel 小工具 — 图形界面版

双击运行，不用命令行。
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    import sys
    tk.messagebox.showerror("缺少组件", "请先安装：pip install pandas openpyxl")
    sys.exit(1)


class App:
    def __init__(self, root):
        self.root = root
        root.title("Excel 小工具")
        root.geometry("620x520")
        root.resizable(False, False)

        style = ttk.Style()
        style.configure("Title.TLabel", font=("", 16, "bold"))
        style.configure("Big.TButton", font=("", 12), padding=8)

        ttk.Label(root, text="Excel 小工具", style="Title.TLabel").pack(pady=(18, 4))
        ttk.Label(root, text="合并 / 去重 / 拆分 / 对比 — 不用装 Excel 插件，不用写公式",
                  foreground="#666").pack(pady=(0, 14))

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=18, pady=(0, 12))

        nb.add(self.tab_merge(nb), text="  合并  ")
        nb.add(self.tab_dedupe(nb), text="  去重  ")
        nb.add(self.tab_split(nb), text="  拆分  ")
        nb.add(self.tab_diff(nb), text="  对比  ")

        self.status = tk.StringVar(value="就绪")
        ttk.Label(root, textvariable=self.status, foreground="#0066cc",
                  anchor="w").pack(fill="x", padx=18, pady=(0, 12))

    # ---------- 通用 ----------
    def _row(self, parent, label, var, cmd, btn="选择..."):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=6)
        ttk.Label(f, text=label, width=12).pack(side="left")
        ttk.Entry(f, textvariable=var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(f, text=btn, command=cmd, width=8).pack(side="right")
        return f

    def _run(self, fn):
        def wrapper():
            try:
                self.status.set("处理中...")
                self.root.update()
                msg = fn()
                self.status.set(msg or "完成")
                messagebox.showinfo("完成", msg or "处理完成")
            except Exception as e:
                self.status.set("出错")
                messagebox.showerror("出错", str(e))
        threading.Thread(target=wrapper, daemon=True).start()

    # ---------- 合并 ----------
    def tab_merge(self, nb):
        f = ttk.Frame(nb, padding=18)
        self.merge_dir = tk.StringVar()
        self.merge_out = tk.StringVar()

        self._row(f, "源文件夹", self.merge_dir,
                  lambda: self.merge_dir.set(filedialog.askdirectory() or self.merge_dir.get()))
        self._row(f, "输出文件", self.merge_out,
                  lambda: self.merge_out.set(filedialog.asksaveasfilename(
                      defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")]) or self.merge_out.get()))

        ttk.Label(f, text="把一个文件夹里所有 Excel 合成一张表，自动加「来源文件」列",
                  foreground="#888").pack(anchor="w", pady=(10, 0))

        ttk.Button(f, text="开始合并", style="Big.TButton",
                   command=lambda: self._run(self.do_merge)).pack(pady=18)

        return f

    def do_merge(self):
        src, out = self.merge_dir.get(), self.merge_out.get()
        if not src or not out:
            raise ValueError("请选择源文件夹和输出文件")

        p = Path(src)
        files = sorted([x for x in p.iterdir()
                        if x.suffix.lower() in (".xlsx", ".xls", ".xlsm")
                        and not x.name.startswith("~$")])
        if not files:
            raise ValueError("文件夹里没有 Excel 文件")

        frames, failed = [], []
        for x in files:
            try:
                df = pd.read_excel(x)
                if df.empty:
                    continue
                df["__来源文件__"] = x.name
                frames.append(df)
            except Exception as e:
                failed.append(f"{x.name}: {e}")

        if not frames:
            raise ValueError("所有文件都没读到数据")

        result = pd.concat(frames, ignore_index=True)
        result.to_excel(out, index=False)

        msg = f"合并 {len(files)} 个文件 → {len(result)} 行"
        if failed:
            msg += f"\n（{len(failed)} 个文件读取失败）"
        return msg

    # ---------- 去重 ----------
    def tab_dedupe(self, nb):
        f = ttk.Frame(nb, padding=18)
        self.dd_in = tk.StringVar()
        self.dd_out = tk.StringVar()
        self.dd_key = tk.StringVar()

        self._row(f, "输入文件", self.dd_in,
                  lambda: self.dd_in.set(filedialog.askopenfilename(
                      filetypes=[("Excel", "*.xlsx *.xls")]) or self.dd_in.get()))
        self._row(f, "输出文件", self.dd_out,
                  lambda: self.dd_out.set(filedialog.asksaveasfilename(
                      defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")]) or self.dd_out.get()))
        self._row(f, "按哪列去重", self.dd_key, lambda: None, btn="")
        ttk.Label(f, text="留空则按整行去重（所有列都相同才算重复）",
                  foreground="#888").pack(anchor="w", pady=(6, 0))

        ttk.Button(f, text="开始去重", style="Big.TButton",
                   command=lambda: self._run(self.do_dedupe)).pack(pady=18)
        return f

    def do_dedupe(self):
        inp, out, key = self.dd_in.get(), self.dd_out.get(), self.dd_key.get().strip()
        if not inp or not out:
            raise ValueError("请选择输入和输出文件")

        df = pd.read_excel(inp)
        before = len(df)
        if key:
            if key not in df.columns:
                raise ValueError(f"找不到列「{key}」\n现有列：{', '.join(df.columns)}")
            df = df.drop_duplicates(subset=[key], keep="first")
        else:
            df = df.drop_duplicates(keep="first")

        df.to_excel(out, index=False)
        return f"{before} 行 → {len(df)} 行（删除 {before - len(df)} 行）"

    # ---------- 拆分 ----------
    def tab_split(self, nb):
        f = ttk.Frame(nb, padding=18)
        self.sp_in = tk.StringVar()
        self.sp_out = tk.StringVar()
        self.sp_by = tk.StringVar()

        self._row(f, "输入文件", self.sp_in,
                  lambda: self.sp_in.set(filedialog.askopenfilename(
                      filetypes=[("Excel", "*.xlsx *.xls")]) or self.sp_in.get()))
        self._row(f, "输出文件夹", self.sp_out,
                  lambda: self.sp_out.set(filedialog.askdirectory() or self.sp_out.get()))
        self._row(f, "按哪列拆分", self.sp_by, lambda: None, btn="")
        ttk.Label(f, text="每个值生成一个文件，比如按「部门」拆，会有销售部.xlsx、技术部.xlsx...",
                  foreground="#888").pack(anchor="w", pady=(6, 0))

        ttk.Button(f, text="开始拆分", style="Big.TButton",
                   command=lambda: self._run(self.do_split)).pack(pady=18)
        return f

    def do_split(self):
        inp, outdir, by = self.sp_in.get(), self.sp_out.get(), self.sp_by.get().strip()
        if not inp or not outdir or not by:
            raise ValueError("请填写完整")

        df = pd.read_excel(inp)
        if by not in df.columns:
            raise ValueError(f"找不到列「{by}」\n现有列：{', '.join(df.columns)}")

        out = Path(outdir)
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for name, group in df.groupby(by):
            safe = str(name).replace("/", "_").replace("\\", "_")[:40]
            group.to_excel(out / f"{safe}.xlsx", index=False)
            n += 1
        return f"拆分成 {n} 个文件 → {outdir}"

    # ---------- 对比 ----------
    def tab_diff(self, nb):
        f = ttk.Frame(nb, padding=18)
        self.df_a = tk.StringVar()
        self.df_b = tk.StringVar()
        self.df_out = tk.StringVar()
        self.df_key = tk.StringVar()

        self._row(f, "表 A", self.df_a,
                  lambda: self.df_a.set(filedialog.askopenfilename(
                      filetypes=[("Excel", "*.xlsx *.xls")]) or self.df_a.get()))
        self._row(f, "表 B", self.df_b,
                  lambda: self.df_b.set(filedialog.askopenfilename(
                      filetypes=[("Excel", "*.xlsx *.xls")]) or self.df_b.get()))
        self._row(f, "输出文件", self.df_out,
                  lambda: self.df_out.set(filedialog.asksaveasfilename(
                      defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")]) or self.df_out.get()))
        self._row(f, "对应列名", self.df_key, lambda: None, btn="")
        ttk.Label(f, text="比如两边都有「订单号」，填「订单号」。留空则按整行对比",
                  foreground="#888").pack(anchor="w", pady=(6, 0))

        ttk.Button(f, text="开始对比", style="Big.TButton",
                   command=lambda: self._run(self.do_diff)).pack(pady=18)
        return f

    def do_diff(self):
        a, b, out, key = self.df_a.get(), self.df_b.get(), self.df_out.get(), self.df_key.get().strip()
        if not a or not b or not out:
            raise ValueError("请填写完整")

        df_a, df_b = pd.read_excel(a), pd.read_excel(b)

        if key:
            if key not in df_a.columns or key not in df_b.columns:
                raise ValueError(f"两边都要有列「{key}」")
            sa = set(df_a[key].astype(str))
            sb = set(df_b[key].astype(str))
            only_a = df_a[~df_a[key].astype(str).isin(sb)]
            only_b = df_b[~df_b[key].astype(str).isin(sa)]
            with pd.ExcelWriter(out) as w:
                only_a.to_excel(w, sheet_name="只在A表", index=False)
                only_b.to_excel(w, sheet_name="只在B表", index=False)
            return f"A 独有 {len(only_a)} 行｜B 独有 {len(only_b)} 行"
        else:
            ra = set(map(tuple, df_a.astype(str).values))
            rb = set(map(tuple, df_b.astype(str).values))
            oa = [r for r in df_a.astype(str).values if tuple(r) not in rb]
            ob = [r for r in df_b.astype(str).values if tuple(r) not in ra]
            pd.DataFrame(oa, columns=df_a.columns).to_excel(out, index=False)
            return f"A 独有 {len(oa)} 行｜B 独有 {len(ob)} 行"


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()

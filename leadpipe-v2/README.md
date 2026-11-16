# leadpipe v2 — 一个会告诉你"我坏了"的采集管道

单文件 Python，零第三方依赖。抓 → 结构化 → 意向分级 → 导出 CSV。

**核心不是能抓，是抓不到的时候你能知道。**

---

## 为什么做这个

我接手过别人的爬虫，几乎每个都有同一个 bug：

**站点改版后，它返回一个空 CSV，然后正常退出。**

cron 按时跑，退出码 0，没有报错，文件每天准时交付——**内容是空的**。

等有人问起来，三周的数据已经丢了。

这个项目的每一行代码，都是为了防止这件事。

---

## 快速开始

```bash
# 1. 自检（不联网，看配置是否完整）
python3 leadpipe.py --check-config

# 2. 跑一次
python3 leadpipe.py --source hn --limit 30 --out out.csv

# 3. 增量（只输出新行）
python3 leadpipe.py --source hn --limit 30 --out out.csv --incremental

# 4. 健康检查（这一步必须有）
python3 guard.py --csv out.csv
```

实测输出：

```
$ python3 leadpipe.py --source hn --limit 30 --out out.csv
[hn] fetching...
output: out.csv
total 30 | A 0 | B 1 | C 29 | failed 0 | 6.4s

$ python3 leadpipe.py --source hn --limit 30 --out out.csv --incremental
total 2 | A 0 | B 0 | C 2 | failed 0 | 6.9s
skipped 28 (already seen)
```

---

## 四个设计决定

### 1. 空结果必须被证明，不能被假设

```python
if not ids:
    raise RuntimeError(
        "list endpoint returned 0 ids — "
        "this is an exception, not 'no data today'"
    )
```

在采集里，空结果确实是合法输出（页面可能今天真的没新内容）。
但**解析挂了也会返回空**。这两种情况必须分开。

分开的方法：看容器本身在不在。
容器在、里面空 → 真空。容器都找不到 → 结构变了，报错。

### 2. guard.py：三道健康检查

| 检查 | 触发条件 | 说明什么 |
|---|---|---|
| 空表 | 0 行 | 可能是完全挂了 |
| 环比骤降 | 比上次少 50%+ | 可能是部分解析失败 |
| 字段完整率 | 某字段低于 80% | 可能是选择器变了 |

```bash
$ python3 guard.py --csv out.csv --baseline 100
异常：out.csv
  · 条数骤降：上次 100 行 → 本次 2 行（降幅 98%）—— 可能是解析部分挂了
  · 字段「signals」完整率仅 0%（阈值 80%）—— 可能是选择器变了或字段缺失
退出码 1
```

**退出码非 0，cron/systemd 就能告警。**

### 3. 增量采集：只抓新的

```bash
python3 leadpipe.py --incremental
# 第一次：total 30, skipped 0
# 第二次：total 2, skipped 28  ← 只输出真正新的
```

游标存在 `~/.leadpipe/state.json`，保留最近 5000 个 key。

**这样每天跑不会把库撑爆，也方便你只看增量。**

### 4. 配置驱动：换站只改 dict

```python
SOURCES = {
    "hn": {
        "kind": "hn",
        "list_url": "https://hacker-news.firebaseio.com/v0/topstories.json",
        "item_url": "https://hacker-news.firebaseio.com/v0/item/{id}.json",
        "site_url": "https://news.ycombinator.com/item?id={id}",
    },
    # 换成客户的站：
    # "shop": {
    #     "kind": "generic",
    #     "list_url": "https://example.com/api/items?page={page}",
    #     "page_start": 1, "page_max": 20,
    #     "items_path": "data.list",
    #     "id_field": "id",
    #     "fields": {"title": "name", "price": "price.current"},
    # }
}
```

**出错时能立刻分清是配置错还是解析错。**

---

## 输出格式

| 字段 | 用途 |
|---|---|
| `unique_key` | md5 去重键，跨次运行稳定 |
| `source` / `source_id` | 哪个源、原始 ID |
| `source_url` | **每行可追溯**，点开能核实 |
| `title` | 原始标题，不做加工 |
| `intent_grade` | A / B / C |
| `intent_score` | 0-10 |
| `signals` | **为什么打这个分**，人能看懂 |
| `fetched_at` | ISO 8601 UTC |

`signals` 是关键——客户能自己复核，不是黑盒。

---

## 部署到客户环境

```bash
# 1. 复制两个文件
scp leadpipe.py guard.py user@host:/opt/leadpipe/

# 2. 建 cron（每天 9 点跑，失败就告警）
0 9 * * * cd /opt/leadpipe && \
  python3 leadpipe.py --source hn --limit 500 --out data/$(date +\%F).csv --incremental \
  && python3 guard.py --csv data/$(date +\%F).csv \
  || echo "leadpipe 异常" | mail -s "采集失败" ops@example.com
```

**注意 `--incremental` 和 `guard.py` 都必须在命令里**，少了任何一个，静默失败的风险就回来了。

---

## 已知局限

- 无代理轮换。目标站若按 IP 限速，需要另配。
- 无验证码处理。
- 无 JS 渲染。需要客户端执行的站要上 Playwright。
- 单源串行（源内并发 8）。多源同时跑需要外层调度。

**写清楚比让人付钱后发现强。**

---

## 文件

```
leadpipe.py    主程序（多源采集 + 意向分级 + 增量）
guard.py       健康检查（空表/骤降/字段完整率）
README.md      本文件
out.csv        实测输出
```

---

MIT License

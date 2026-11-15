# 线索采集管道（可跑演示）

一个能直接跑的采集 → 结构化 → 意向分级 → 导出 CSV 的管道。
换目标站只改 `SOURCES` 里一个配置，不动代码。

## 跑一次

```bash
python3 leadpipe.py --source hn --limit 60 --out leads.csv
```

实测输出：

```
输出: leads.csv
总数 60 | A 1 | B 0 | C 59 | 失败 0
```

## 输出长这样

| unique_key | source_url | title | intent_grade | intent_score | signals | fetched_at |
|---|---|---|---|---|---|---|
| 9ca13807… | news.ycombinator.com/item?id=50441444 | Generative AI uses more energy… | C | 2 | 技术需求相关 | 2026-11-15T12:22:22+00:00 |
| a8b6b2fb… | news.ycombinator.com/item?id=50499017 | Lovable apps expose passport details… | C | 2 | 技术需求相关 | 2026-11-15T12:22:06+00:00 |

字段说明：`unique_key` 去重用、`source_url` 可追溯、`signals` 说明为什么打这个等级（客户能自己复核）。

## 四个设计决定

**1. 配置驱动，不硬编码**
每个源就是一条配置：一个列表接口 + 一个详情接口。换平台 = 加一条配置。

**2. 抓不到就报错，不返回空表**
列表接口返回空 → 直接退出并说明"这是异常，不是没有数据"。
这条是踩过坑的：静默返回空表，客户会以为"今天没线索"，实际是解析挂了。

**3. 幂等去重**
`unique_key = md5(source + 原始ID)`，重复跑不会产生重复行。每天定时跑不会把库撑爆。

**4. 意向分级可解释**
不是黑盒打分。每条线索带 `signals` 字段，写明命中了哪些关键词（招聘/预算/技术需求…）。
客户看到 A 级线索，能自己判断该不该跟。

## 换到真实场景要改什么

```python
SOURCES["客户平台"] = {
    "list_url": "https://.../api/list?page={page}",
    "item_url": "https://.../api/detail/{id}",
    "site_url": "https://.../item/{id}",
}
```

外加：
- 有登录态的源，接客户自己的账号（不碰别人的）
- 有频控的源，加限速和 Retry-After 服从
- 字段映射按客户要的表头调 `rows.append({...})`

## 没做的事（说清楚）

- 没做分布式，单机够用；数据量上来再加
- 没做代理池，演示源不需要；真实场景按需
- 分级规则是关键词打分，不是模型；接 LLM 可以，但要先证明规则版够用

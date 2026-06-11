# Personalized Research Dashboard

这是一个面向个人研究方向的 arXiv 论文筛选与复审系统，不再是传统的“按关键词生成日报”的通用项目。

当前仓库的核心目标是：

- 先冻结某一天的论文池 `pool`
- 再围绕你的研究画像做加权 L1 相关性筛选
- 对入围论文做 L2 可行性复审
- 生成 markdown 形式的 digest
- 用 Astro 把 `Digest / L2 / L1 / Archived` 按研究方向可视化展示出来

## 1. 系统概览

当前流程以 `pool date` 为主键，而不是论文自己的 `published_date`。

这意味着：

- 你在 web 端切换日期时，看到的是某一次固定检索池中的论文
- 这个池里的论文可以来自更早的 arXiv 日期
- 后续 L1、L2、Digest 都围绕这个固定池展开，便于复现、回看和断点续跑

主流程如下：

```text
arXiv / 数据源
  -> 检索并冻结 pool
  -> L1 抽象级相关性筛选
  -> L2 全文级可行性复审
  -> Digest 总结与 watchlist
  -> Astro Web Dashboard
```

## 2. 研究画像与权重

研究方向配置位于 `configs/research_profile.yaml`。

当前支持 1-5 级权重，5 级最高。项目会把这些权重显式用于：

- L1 相关性判断
- L2 复审优先级
- Web 端分组展示顺序
- Digest 中的重点排序

当前方向结构：

1. 大模型训练数据集制备与评测数据集，重点关注情感、多轮对话、tool use、SFT、RL、on-policy distillation（4级）
2. 大模型记忆，重点关注多智能体记忆框架、长期记忆、个性化记忆、人格一致性、情绪稳定性、隐式记忆索引（5级）
3. 神经科学与自然语言和记忆交叉（1级）
4. 大模型训练加速与推理加速（2级）
5. POI 场景与 AI 结合，重点关注陪伴产品中的 tool use 与场景化能力（3级）

项目中的一个重要原则是：

- 一篇论文只需要命中一个核心方向，就可以被视为相关
- 不允许在分析中强行拉扯到无关方向
- 评测、负面评估、可靠性审计本身可以是高价值方向，不需要被硬绑定到“系统落地”或“多方向同时命中”

## 3. 目录结构

当前 personalized 产物主要在 `docs/personalized/` 下：

```text
docs/personalized/
  pools/YYYY-MM-DD.json
  l1/YYYY-MM-DD.json
  l1/YYYY-MM-DD.md
  l2/YYYY-MM-DD/*.json
  digest/YYYY-MM-DD.md
  runs/YYYY-MM-DD.json
  runs/latest.json
  cache/
  logs/YYYY-MM-DD/
    pipeline.json
    l1.json
    l2.json
    digest.json
```

重点说明：

- `pools/YYYY-MM-DD.json`
  这是当天固定下来的论文池，也是 web 端日期筛选的基础
- `l1/YYYY-MM-DD.json`
  记录 L1 相关性筛选结果
- `l2/YYYY-MM-DD/*.json`
  每篇论文的 L2 review 输出，当前已从旧的 `reviews/` 路径迁移过来
- `digest/YYYY-MM-DD.md`
  最终 markdown 日报，当前已从旧的 `daily/` 路径迁移过来
- `logs/YYYY-MM-DD/*.json`
  各阶段结构化日志，是 web 端最稳定的数据入口

## 4. Web 展示

前端位于 `web/`，使用 Astro。

当前 web 端已经围绕 personalized pipeline 重构，核心行为是：

- 左侧工具栏按 `pool date` 切换
- 中间内容固定按四栏展示：
  - `Digest`
  - `L2`
  - `L1`
  - `Archived`
- 每一栏内部再按研究方向分组
- `Digest` 直接渲染 markdown 内容，并附带对应论文卡片
- 同一篇论文只会展示在最深阶段，避免多栏重复

这和旧版 keyword/month 网站已经不是同一套信息架构。

## 5. 运行方式

### Python 流程

```bash
uv run python -m nlp_arxiv_daily run-personalized --date 2026-06-11
```

如果只想调试某一个阶段：

```bash
uv run python -m nlp_arxiv_daily filter-l1 --date 2026-06-11
uv run python -m nlp_arxiv_daily review-l2 --date 2026-06-11
uv run python -m nlp_arxiv_daily build-digest --date 2026-06-11
```

### Web 开发

```bash
cd web
pnpm install
pnpm dev
```

构建静态站点：

```bash
cd web
pnpm build
pnpm preview
```

## 6. 关键配置与 Prompt

- 主配置：`config.yaml`
- 研究画像：`configs/research_profile.yaml`
- L1 Prompt：`prompts/l1_abstract_filter.md`
- L2 Prompt：`prompts/l2_paper_review.md`

这些文件共同决定：

- 检索方向
- 方向权重
- L1 通过/归档/拒绝逻辑
- L2 的相关性、可行性与动作建议
- Digest 中的重点排序方式

## 7. 当前项目与旧项目的关系

这个仓库已经明显偏离了最初的“关键词 arXiv 日报”模式，但为了保持项目沿革完整性，仍然保留以下 reference：

- [monologg/nlp-arxiv-daily](https://github.com/monologg/nlp-arxiv-daily)
  这是本项目公开谱系中最直接的上游参考，提供了 NLP/LLM 论文跟踪、Astro 静态发布、搜索/RSS 等基础模式。
- [Vincentqyw/cv-arxiv-daily](https://github.com/Vincentqyw/cv-arxiv-daily)
  更早的 arXiv-daily 思路来源。

当前仓库相对这些项目的主要变化：

- 从“按关键词聚合”转向“按个人研究画像分级筛选”
- 从通用日报转向 L1/L2/Digest 的多阶段评审系统
- 从月度归档为主转向 `pool date` 快照驱动
- 从统一列表展示转向按研究方向、按阶段分栏展示
- 更强调评测、负面评估、可靠性和 toC 相关性

## 8. 适用场景

这个项目更适合以下用法：

- 做个人研究雷达，而不是做公共广场式榜单
- 对某几个高优先级研究方向进行持续审阅
- 希望把“相关性筛选”和“可行性复审”拆开
- 希望保留每天的固定候选池，便于复盘与审计
- 希望最终产物既能机器消费，也能通过 web 人类浏览

## 9. 后续可扩展方向

当前结构已经比较适合继续扩展：

- 更细粒度的方向标签可视化
- L2 结论和 digest watchlist 的联动筛选
- 针对单篇论文的详情页
- 方向趋势统计和跨日期对比
- 更强的 review cache 与失败重试可视化

## 10. Integrity Reference

为了保证项目来源清晰，这里保留上游引用：

- [monologg/nlp-arxiv-daily](https://github.com/monologg/nlp-arxiv-daily)
- [Vincentqyw/cv-arxiv-daily](https://github.com/Vincentqyw/cv-arxiv-daily)

当前项目在理念上承接了它们的 arXiv daily workflow，但已经演化为一个面向个人研究决策的 personalized review system。

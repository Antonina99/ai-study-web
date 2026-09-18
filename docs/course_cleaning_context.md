# AI 课程转写校订上下文

用于 transcript-fixer 的 `--scan-traps --context-file`。先对照原始 DOCX 和技术语境，再判断候选；不要把扫描命中当作已确认错误。

- **`Retrieve as you Go` → RAG** — 全称应为 Retrieval-Augmented Generation；用户纠正，原文 22:19 与 https://arxiv.org/abs/2005.11401 一致。
- **`evening模型`/`inventing模型`/`invention模型` → Embedding 模型** — 仅限把文字转换为向量的语境，禁裸词；不可替换普通英语 evening。
- **`in contest learning` → In-Context Learning** — 在提示词中放参考资料或示例的语境，禁裸词。
- **`Agented RAG` → Agentic RAG** — 查询改写、路由与检索编排语境，参考 https://docs.langchain.com/oss/python/langgraph/agentic-rag 。

## 内容边界

保留原始转写和 original-N，校订仅进入学习派生版本。RNG、REG、cos、tree、GM5.1 等具有歧义或可能指向别的概念，不做跨课程裸词替换。不猜测人名、型号、数值，也不把讲师观点静默改写成其“原话”。无法确认的片段不作为知识结论传播；仍可在原文中核查。

## 长文流程

先提取 DOCX → 划分真实章节（排除导读附加的问答/PPT 重复章节）→ skill 词典初筛 → 通读上下文校订 → 整理学习主题、证据与条件 → 独立复核 → 检查数字、否定与主题覆盖 → 按源指纹应用。

原稿校对与学习版摘要是不同产物。摘要可以过滤闲聊并压缩，原稿引用必须保留原貌。规则扫描不能替代整课语义复核。

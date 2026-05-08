# Orchid 项目协作说明

> 一个面向工作流编排的 AI 智能体框架。强调成本可预测、执行可审计、技能可验证。
> 自托管、MIT 许可，可直接 `docker-compose up` 起跑。

本文用于向潜在合作者介绍项目当前状态、市场定位、商业价值与下一步规划。
观点尽量克制——做基础设施工具的真实回报通常远低于路演 PPT 的描述，
我们更希望与认同长期价值的合作者一起做事。

---

## 1. 项目简介

**Orchid** 是一个开源的 AI 智能体工作流编排框架。和市面常见的「自托管聊天网关 +
AI 助理」（如 OpenClaw 系）不同，Orchid 的核心抽象是**工作流**，而不是对话：

- 单 Agent 任务、DAG、Pipeline、Group（编排者+工人）、Passthrough（确定性工具调用）
  共五种工作流类型
- 所有外部技能在沙箱容器（skill-runner）中执行，与主进程隔离
- 内置预算追踪、运行事件流（DB 持久化、可回放）、WebSocket 实时推送
- 统一通过 LiteLLM 接入主流模型提供商（Anthropic / OpenAI / OpenRouter / Ollama 等）

技术栈：Python (FastAPI) + Postgres + Redis + 独立 skill-runner 容器 + Next.js 前端。

---

## 2. 当前进展（What's Present）

### 已实现的核心能力

**工作流引擎**
- 五种工作流类型，全部由统一的 `_llm_loop` 工具调用循环驱动
- Pipeline 步骤间通过 `previous_output` 自动传递
- 单一队列消费者，支持优先级与崩溃恢复
- 任务可配置 `input_schema`，前端自动生成参数表单

**沙箱化的技能系统**
- skill-runner 是独立 Docker 容器，主进程通过 HTTP 代理调用
- 内置技能（bundled）：放在 `backend/app/skills/bundled/`，启动时挂载到容器
- 外部技能：通过 npm/pnpm/git 安装到 `./skills/`，与 bundled 同样的加载机制
- 已有 11 个学术检索技能（arXiv、Semantic Scholar、OpenAlex、DBLP、CrossRef、
  ACL Anthology 等）以及 web_reader、multi_search 等通用技能

**内置工具**（在主进程执行，非沙箱）
- vault 系列（项目化文件存储，支持嵌套路径）
- gmail_send、wechat_publish、generate_image、replicate_generate_images、
  text_to_speech、web_search、http_request 等

**已可演示的工作流模板**
- `bedtime-story-pipeline.json`：故事生成 + 配图 + TTS + 推送
- `professor-research-pipeline.json`：教授信息聚合 + 研究方向分析 + 报告
- `research-directions-pipeline.json`：研究方向调研，自动生成 2025 年综述
  报告 + 2026 年新论文报告

**基础设施**
- 预算追踪（`check_budget` / `record_usage`），可在运行中触发停止
- 事件流写入 DB，前端通过 WebSocket 实时订阅
- 工具描述做了 token 优化，避免重复占用 prompt 缓存
- 时间戳精确到日（而非分），保护 Anthropic prompt cache

### 近期的工程优化

- 重写 `web_reader`：新增 `query` 参数，按相关性筛选段落，剥离 nav/cookie/侧栏，
  优先抽取 `<main>`/`<article>` 区块，PDF 用 pypdf 解析
- 重写学术论文 fetcher：紧凑三行格式（节省约 30% token），按句号截断摘要
- 工具/技能描述全部从「操作说明」改为「选择标准」，配合带描述的内置规则降低
  agent 在多个相似工具间的选择失误
- 删除已废弃的进程内技能加载路径，统一通过 skill-runner 沙箱执行

---

## 3. 市场对比（Commercial Comparison）

### 类别归属

Orchid 与其说是「OpenClaw 类」（自托管聊天网关 + 助理），不如说更接近
**LangGraph / Mastra / CrewAI** 这一类工作流编排框架，但具备 OpenClaw 系的
自托管基因和技能市场设计。

| 维度 | OpenClaw 系（含 Tencent WorkBuddy / 阿里 / NemoClaw / IronClaw 等） | LangGraph / Mastra / Crew | **Orchid** |
|---|---|---|---|
| 主要单元 | 聊天会话 | 工作流图 | 工作流（5 种类型） |
| 触发方式 | 即时消息（WhatsApp/Slack/Discord 等） | API 调用 / 调度器 | API 调用 / 调度器 |
| 多渠道聊天网关 | ✅ 核心特性 | ❌ | ❌（不进入此战场） |
| 技能/工具沙箱 | OpenClaw 主进程直接执行；NemoClaw/IronClaw 用 wrapper 加固 | ❌ 普遍无 | ✅ 独立容器 |
| 多种工作流类型 | ❌ 仅会话 | ✅ | ✅ |
| 成本预算硬中断 | ❌ 仅事后账单 | ❌ | ✅ 已实现，正在升级到事前预测 |
| 可回放的运行日志 | ⚠️ 部分 | ⚠️ 部分 | ✅ 事件流持久化 |
| 自托管 + MIT | ✅ | ⚠️ LangGraph 有 BSL 限制 | ✅ |

### OpenClaw 生态的现状（2026 年 4 月）

- **官方仓库压力极大**：维护方在 2026 年 3 月引入「每作者最多 10 个 open PR」的
  限制，结构性 bug（如 QMD 内存后端的 20+ issue / 15+ PR）只能由官方协调修复
- **CVE-2026-25253**（CVSS 8.8）：通过 localhost WebSocket 跨站劫持实现一键 RCE
- **ClawHavoc 供应链事件**：1184 个恶意技能包，9000+ 安装受影响
- **子 Agent 通知死循环 #43802**：3 分钟内 100+ API 调用、442k token 被消耗

商业 wrapper（Tencent WorkBuddy/QClaw/ClawPro、阿里云 Model Studio、NemoClaw、
KiloClaw 等）各加一层 UI / 多模型 / 计费 / 沙箱，但**结构性问题无法通过 wrapper
修复**——这是大厂选择 wrap 而不是重写的硬约束。

### 已有的从零重写竞品

8 周内出现了 4 个全新实现，合计约 11.6 万星：
- **Nanobot**（Python，HKU，2.68 万星，4000 行代码）— 主打极简
- **ZeroClaw**（Rust，3.4MB 单文件）— 主打 $10 嵌入式硬件
- **PicoClaw**（Go，Sipeed）— 主打 RISC-V / 硬件生态
- **NanoClaw**（TypeScript）— 主打 Anthropic Agents SDK 生态

**这条赛道不缺极简、不缺资源效率、不缺安全 wrapper。缺的是「可预测成本 +
可审计执行 + 可信任技能」的工作流编排器**——这正是 Orchid 的定位空隙。

---

## 4. 商业定位（Commercial Positioning）

一句话定位：**「LangGraph，但你的财务团队不会因为账单跟你急」**

具体差异化主张：
1. **执行前的成本中断**：现有平台都是事后账单。Orchid 在工具调用真正发生前
   预估 token 成本，超阈值要求显式批准。直接对标 OpenClaw 子 Agent 死循环这
   类已知痛点
2. **签名技能注册表**：每个上架技能都在 CI 中沙箱跑通、签名背书、声明所需
   网络出口与文件访问范围。直接对标 ClawHavoc 类供应链攻击
3. **沙箱化的技能运行时**：技能进程与主框架解耦，未来商业版可平替为按
   运行隔离的 microVM（Firecracker / gVisor）
4. **可回放的运行日志**：所有事件持久化，「上个月那次 50 美元的运行到底
   做了什么」可以被还原，是 LangGraph 类用户长期投诉的点

不做的事（写在路线图里以避免漂移）：
- 不做多渠道聊天网关（OpenClaw 的强项，没必要正面对撞）
- 不做内置认证（让外部反向代理处理，框架仅信任 header）
- 不做内置 microVM（留给商业产品 `orchid-platform`）
- 不做模型代理（LiteLLM 已经够了）
- 不参与「最少代码行数」的极简竞赛（我们有 Postgres、队列、前端、市场，
  这是基础设施，不是 toy）

---

## 5. 下一步规划（What's Next）

完整版见 [`future.md`](future.md)。这里只列分层的关键节点：

### 第一阶段：商业化拆分的地基（4-6 周）

- **skill-runner HTTP 契约固化**：让未来的 microVM 运行时实现同样接口而无需 fork
- **`tenant_id` 全表加字段**：现在加一句迁移，将来加是几周工作量
- **Auth 代理契约**：框架不实现认证，强制要求生产环境通过反向代理
- **Dry-run 成本预测**：本阶段最重要的功能，是对外 demo 的核心卖点

### 第二阶段：产品差异化（1-3 个月）

- **AI 技能编写器** + **签名技能市场**（合作者关心的核心模块之一）
- **计划驱动的编排器工作流**（第六种工作流类型，agent 可灵活调用其他任务）
- **持久化记忆层**（CrewAI/Mastra/Google ADK 才有，LangGraph 都没有）
- **OpenTelemetry 链路追踪 + 运行回放 UI**
- **Eval 测试框架**（避免 prompt 调整变成无保险的生产改动）

### 第三阶段：商业产品 `orchid-platform`（3-6 个月）

- **每运行 microVM 沙箱**（Firecracker / gVisor / Kata）
- **多租户 + 计费**（接 Stripe，按运行/按 token 计量）
- **一键部署**（Helm / Coolify / VPS 安装器）
- **签名技能市场前端**

---

## 6. 商业价值（Commercial Value）

### 可能的变现路径

| 路径 | 优势 | 劣势 | 18 个月可能营收 |
|---|---|---|---|
| **OSS + 赞助 / 咨询** | 启动成本低 | 单人天花板低 | $0–50k |
| **Open-core SaaS**（OSS 框架 + 商业 platform） | 标准开源商业模式 | 需要团队和销售 | $50–500k |
| **垂直 SaaS**（基于框架的成品工作流） | 直接面对终端用户、易定价 | 需要选对赛道 | $30–300k |
| **企业私有部署 + 咨询服务** | 单笔金额大 | 销售周期长，需 SOC2 / 法务 | $100k–1M |

### 现实预期分布（个人独立开发，12-18 个月投入）

- **70% 概率**：项目获 200–1,500 GitHub 星，小社区，营收 $0-5k，作为作品集
- **20% 概率**：5,000-15,000 星，吸引细分用户，靠咨询/赞助维持 $30-150k/年
- **8% 概率**：被认真采用，可能拿到种子轮（$1-3M），组建 3-5 人团队
- **2% 概率**：突破式增长（LangChain 量级）

参考：LangChain 月下载量 3,400 万但商业化仍困难；Mastra 拿到 $5M 种子但尚未盈利；
Vellum / Lindy / Relevance AI 的创始人都有 GTM 背景。基础设施工具的 time-to-revenue
在所有软件类别中排名最差（最少 18-24 个月）。

### 反直觉建议

考虑同时做一个**垂直 SaaS 验证市场**。Orchid 已经有几个可以直接产品化的工作流模板：

- **ResearchScout**（基于 `research-directions-pipeline`）：面向博士后、PI、
  申请基金的研究人员，$49-99/月
- **ProfScout**（基于 `professor-research-pipeline`）：面向研究生申请者，$29-49/月
- **ContentScout**（基于 `bedtime-story-pipeline` 抽象）：面向独立创作者，$19/月

8 周内拿到 10 个付费用户的话，框架本身的商业前景会被「真实付费客户」的需求拉着走，
比闷头建基础设施 6 个月有更好的信号。

---

## 7. 预期产出 / 招募方向

### 我们希望的合作者类型

- **后端 / 基础设施工程师**：参与第一阶段地基（HTTP 契约、多租户、沙箱契约）
- **安全工程师**：参与签名技能注册表、CVE 防御、microVM 集成
- **前端 / 产品**：负责工作流可视化编辑器、运行回放 UI、技能市场前端
- **GTM / 内容**：会写技术博客、能玩 HN/Twitter、能做 demo 视频
- **销售 / BD**：如果走 open-core SaaS 路线，需要懂开发者工具销售
- **垂直产品负责人**：如果同步做 ResearchScout / ProfScout 类垂直产品

### 协作模式（待商议）

- 早期：核心贡献者获得后续商业版的股权 / 收益分成（具体比例按贡献量协商）
- 全职/兼职均可
- 如走 open-core 路线：核心 OSS 框架不会闭源，承诺 MIT 不变
- 如走垂直 SaaS 路线：可独立融资或 bootstrapping

### 我们对自己的预期

- 12 个月内：完成第一阶段地基 + 第二阶段一半，OSS 框架达到「陌生人能跑通非
  trivial 工作流」的水平，启动垂直 SaaS 验证
- 24 个月内：根据上述信号决定是组建团队全力做 platform 还是聚焦垂直 SaaS
- 不承诺：超大规模融资、IPO 路径、Unicorn 故事——这些不在我们的预设之内

---

## 8. 联系方式

（合作意向 / 反馈 / 提问请联系项目维护者，邮箱见仓库）

---

*本文档反映 2026 年 4 月的项目状态与市场判断。会随项目和市场变化更新。*

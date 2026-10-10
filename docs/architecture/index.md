# 架构导航

Career Workbench 的架构说明分三层,按阅读顺序:

| 层 | 内容 | 链接 |
|---|---|---|
| 系统上下文(L1) | 谁使用系统、系统连接什么外部世界 | [c4-context.md](./c4-context.md) |
| 容器(L2) | 本机内可运行的进程与数据存储 | [c4-containers.md](./c4-containers.md) |
| 交互式架构图 | Archify 生成的可缩放/可检索视图(自包含 HTML) | [../../assets/career-architecture.html](../../assets/career-architecture.html) |
| 黄金旅程工作流 | 一次真实端到端运行的门禁流(交互式 HTML) | [../../assets/career-golden-journey.html](../../assets/career-golden-journey.html) |

对应可编辑图源与静态渲染图在 `assets/`:`c4-context.mmd` / `c4-containers.mmd`(Mermaid C4 语法)与同名 `.svg`/`.png`。

## 禁止存在的关系(设计红线)

以下关系**不存在**于任何实现中,并且有证据约束:

- 任何 Agent/模型 → 发送或投递申请:不存在 send/submit 工具;不可逆动作只能由人执行。
- Agent → 覆盖 master 简历:master 是只读输入;草稿写入 drafts 目录。
- 浏览器/模型 → 伪造 Owner 审批:bridge 只接受 Host 进程秘钥签署的 `OWNER_UI` 通道(`career_v0/bridge.py` 头部契约)。

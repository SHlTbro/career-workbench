# 验证与证据

本包的声明均可在导出源码与本文件列出的运行记录中核对。生成日期:2026-10-07。

## 真实端到端(黄金旅程,2026-09-29)

无 fixture、无 mock 的一次完整运行:

1. G0:Owner 本人确认战役偏好(3 项保护身份信号逐字核对)。
2. 搜索:51 条真实来源线索(DSH web_search)。
3. 抓取/归一化:16 条真实归类(合格 2 / 待核实 8 / 排除 6)。
4. G1:Owner 从批次中选定 1 个岗位。
5. M2:研究 READY_FOR_PLAN(完整 JD)→ 计划 rev1 → Owner 退回 → rev2 → G2 批准。
6. PDF:2 页 A4 / 4 HERO / 7 项目 / 机械 QA 全绿。
7. G3:Owner 视觉批准(三项检查)。
8. Handoff:zip 包 8/8 文件齐全(278KB),含完整 JD、研究、PDF 与面试研究提示。

## 启动器实跑(2026-10-07,本包验证时)

- `start-workbench.ps1`:端口占用自检 → DSH Web 启动 → 认证 URL 抓取 → HTTP 复验通过,URL 落盘。
- 认证 URL:HTTP 303(token 换 cookie)实测;匿名访问 API 返回 401。
- 已知怪癖:DSH 启动早期可能重派生进程,早期 token 随之失效——启动器会取日志最后一条 URL 并做 HTTP 自纠;若手动粘贴 URL 遇 401,取状态目录 `logs/dsh-web-last.out.log` 中最后一条 `dsh web:` 链接即可(本项目文档记录的兜底路径)。
- `stop-workbench.ps1`:STOP PASS,端口释放实测。
- 启动期唯一警告:`office-to-pdf` 插件 import 失败——不影响 Career 自带渲染链(独立 Playwright 路径),已知非阻塞项。

## 测试

- 56 个单元/集成测试(`python -m unittest discover -s career_v0/tests -t .`)。
- 2026-09-27 验收记录:56/56 全过。
- 2026-10-07 复跑:55/56,1 个分类规则测试未同步 2026-09-28 的 Owner 放宽规则(详见 [capabilities.md](./capabilities.md) 测试状态节)。测试在导出树内原样复现(56 跑、同 1 败),证明包内容与源一致。

## 已知限制

- Windows 优先:启动/停止脚本为 PowerShell;渲染链依赖本机 Chromium 构建(可用环境变量 `CAREER_PLAYWRIGHT_MODULE` / `CAREER_CHROMIUM_PATH` 指向)。
- 启动/停止脚本与 `tools/truth-guard.py` 内含需要按机器填写的路径常量(详见 README 快速安装)。
- 渲染链依赖本机的 Node 与 Playwright Chromium:渲染测试通过 `CAREER_NODE_BIN` / `CAREER_PLAYWRIGHT_MODULE` / `CAREER_CHROMIUM_PATH` 环境变量指向本机安装(未设置时按 PATH 解析 Node);无相关安装的机器上渲染 QA 测试会报错,配置后重跑即可。
- 搜索 provider 约束见 [capabilities.md](./capabilities.md)。

## 证据原始记录

完整研发证据(运行时版本实采、manifest 门禁、invocation 日志、truth-guard 报告)保存在项目私有目录,不随本包分发;本文件只引用其结论。包内可核对的证据 = 导出源码 + 本文件描述的可复现命令。

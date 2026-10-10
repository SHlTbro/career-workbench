# 能力与边界

状态词汇:**已实现**(有引用证据)· **已设计**(有设计,未构建)· **不可用**(尝试过,被阻塞)。状态不是性能指标。

## 已实现

| 能力 | 证据 / 说明 |
|---|---|
| G0 战役偏好确认(角色/城市/薪资基准/未知薪资策略/输出格式/三保护身份信号) | `career_v0/domain.py` validate_campaign_preferences;黄金旅程 CMP-4F72804FE1934C49B00B |
| 真实岗位搜索(headless) | DSH web_search 桥;黄金旅程 51 条真实线索 |
| 抓取 + 归一化三池(qualified/unknown/excluded) | `career_v0/discovery.py`;黄金旅程 16 条(2/8/6);搜索结果只计线索,绝不自动计为合格 |
| 候选批次 XLSX 往返(导出 → 外部编辑 → 上传预览) | `career_v0/workbooks.py`;Host `_uploads` 临时文件 + 10MB 上限 |
| 裁剪计划 + G2 批准(修订环) | `career_v0/plans.py` + `plan_workbooks.py`;黄金旅程 rev1 → Owner 退回 → rev2 → G2 批准 |
| 证据绑定简历内容(HERO/COMPACT 分层) | `career_v0/resume_content.py`;黄金 PDF 4 HERO / 7 项目 |
| PDF 渲染 + 机械 QA(页数/项目齐全/保护文本/紧凑行预算) | `career_v0/render_resume.mjs` + `resume_render.py`;2 页 A4 QA 全绿 |
| G3 视觉批准 + Handoff 压缩包 | 黄金旅程 G3 批准;handoff zip 8/8 文件 278KB |
| Owner 动作认证(浏览器不可伪造审批) | `career_v0/bridge.py` 进程级秘钥契约;匿名 401 实测 |
| Truth Guard 证据声明校验 | `tools/truth-guard.py`(确定性文本分析,非 LLM);`tests/test_truth_guard.py` |
| 一键启动/停止 Launcher(URL 自纠错 + 端口直查) | `career_v0/start-workbench.ps1` / `stop-workbench.ps1` |

## 已设计(未构建)

| 能力 | 说明 |
|---|---|
| 多战役导航/历史 UX | 现有批次/导出/预览可跨刷新恢复;多战役切换体验待打磨 |
| 通知草稿(飞书/邮件 Draft 级) | 依赖外部凭据;当前以文件产物为通知面 |

## 不可用 / 限制

| 项 | 现状 |
|---|---|
| 公司公开源搜索 provider | 默认端点余额不足或无联网插件时,公司研究档案不可用;JD-first 主流程不受影响(黄金旅程即 JD-first 完成) |
| 真实公司源过页 | 公司研究的公开来源链路已在合成测试中验证(`tests/test_company.py`);真实公司源尚未经 Web 页面走完 |
| 自动投递 / 自动发送 | 永不实现(设计红线):无 send/submit 工具;投递永远人工 |

## 测试状态(如实)

- 验收套件 56 个测试;2026-09-27 记录的验收运行为 56/56 全过。
- 2026-10-07 复跑:55/56。失败项 `test_unknown_role_experience_jd_and_opening_never_count_as_qualified` 仍按 2026-09-28 规则放宽前的旧预期断言(缺失 JD 完整度 ⇒ unknown 池),而产品规则已按 Owner 决定放宽(`career_v0/domain.py` 内注释)。属测试预期与放宽后规则未同步,待 Owner 裁定是改测试还是收紧规则;在裁定前,本 README 不声称测试全绿。

# 项目开发团队

状态：讨论与设计阶段。已完成前后端、用户、对话与记忆方案，尚未编写应用或执行验收。完整实施计划见 project-plan.md。

## 产品决策

- 本地单用户 Web 工作台；通用短视频，优先故事短片。
- 简短介绍 → 故事扩写与确认 → 分镜及逐秒剧本 → 编辑/范围重写 → 检查 → 导出。
- 支持本地用户档案、项目对话、来源可追溯的上下文摘要、用户确认的项目记忆与长期偏好。
- 每秒保留可编辑剧本与 Prompt；连续分镜 Prompt 是主要生成导出对象。
- 视频由用户在外部模型生成。第一版默认离线示例，示例与真实模型结果分别标记。

## 分工与写入边界

| 成员 | 职责 | 实现阶段负责目录 |
| --- | --- | --- |
| 主 agent | 需求取舍、接口冻结、任务拆分、集成、风险判断、交付 | 根目录文档、环境、Git、docs/、集成配置 |
| architecture_backend | 数据契约、API、持久化、生成编排、用户/会话/记忆、模型适配 | backend/、agents/、tools/、skills/、workflows/、prompts/、context/、memory/ |
| frontend_design | Apple 风格界面、逐秒编辑、分镜、聊天、记忆管理、版本与导出交互 | frontend/ |
| testing_evals | 独立契约检查、接口回归、记忆隔离及失效、真实浏览器验收、质量评估 | tests/、evals/、docs/validation.md |

并发上限为主 agent 加三个子 agent。子 agent 发现其他目录问题时向主 agent 报告，由负责者修复；不覆盖其他成员文件。共享 API 或依赖变更先由主 agent 更新契约，再通知消费者。最终集成和本地提交由主 agent 执行。

## 协作流程

1. 冻结输入输出契约、时间规则与验收条件。
2. 前后端分别实现；测试成员根据契约准备独立测试。
3. 前后端联调，测试成员复现并提供代码位置、步骤与证据。
4. 负责成员修复；测试成员回归；主 agent 复现关键问题并集成。
5. 记录真实通过、失败与未验证项，交付启动说明与项目文档。

时间采用半开区间 [start, end)，时长 N 秒必须覆盖 [0,N)，无缺秒和重叠。异步写入携带基础版本，迟到结果不能覆盖用户最新修改。范围重写先保存候选，用户应用后创建版本。

## 技能与来源

- 前端：本机 apple-interface-design。
- 浏览器与跨层测试：本机 fullstack-gui-testing。
- 里程碑独立审查：本机 high-intensity-testing，实际采用时按其适用流程执行。
- 社区候选：https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md 。已读取供筛选，未安装或采用完整流程。
- 官方精选目录已查询，未发现名为 agent-teams 的专用技能。
- 协作官方参考：https://developers.openai.com/api/docs/guides/agents-api/multi-agent 。当前开发团队使用本会话已有协作工具。

## 验收和成本边界

- tests/ 验证程序行为；evals/ 验证任务输出质量，维护 50 个固定场景。
- 机械检查与人工故事质量评价分开记录；离线示例通过不能证明真实模型质量。
- 记录 Token、耗时、重试、成功率；费用缺少依据时为未知。
- API Key 仅后端读取；.env.example 只放假值/说明，.env 初始空值并被 Git 忽略。
- 付费 API 调用、GPU 租用和付费部署需用户批准；当前无此授权。
- 新增依赖说明用途，固定版本并提交锁文件；外部代码复用前核验许可证。

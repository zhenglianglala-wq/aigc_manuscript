# AIGC 视频编剧工作台

本地单用户项目：通过简短介绍生成扩写故事、逐秒剧本和连续分镜 Prompt，并提供项目对话与用户确认的记忆。视频由用户在外部模型生成。

当前处于设计阶段，尚无可启动应用。

- [完整项目计划书](docs/project-plan.md)
- [开发团队与协作边界](docs/agent-team.md)
- [代码边界与测试要求](agent.md)

远端仓库：https://github.com/zhenglianglala-wq/aigc_manuscript

`.env.example` 是无密钥配置模板；本机 `.env` 仅含空值变量，已加入 `.gitignore`。

实施将采用 React + TypeScript 前端、FastAPI 后端和 SQLite，完成后补齐环境、启动、配置、测试与备份说明。付费调用需用户批准；配置模板不会包含真实 API Key。

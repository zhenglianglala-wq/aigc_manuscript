# 项目代码与协作边界

已实现本地工作台。完整方案见 docs/project-plan.md；接口见 docs/api-contract.md；团队见 docs/agent-team.md。验收状态以 docs/validation.md 为准，离线测试不代表真实模型效果。

## 目录职责

- frontend/src/app/App.tsx：工作台协调；features/：用户、项目、对话、记忆、分镜与候选；styles/：主题材质；api/：HTTP 与下载。
- backend/main.py：FastAPI 入口、API 和配置；schemas.py：边界校验；store.py：SQLite 事务、版本与数据库版本检查。
- agents/：角色判断与结构化输出，不直接访问数据库。
- tools/model.py：兼容文本接口和受批准的调用；compiler.py：逐秒/分镜 Prompt 和机械检查。导出目前位于 backend/main.py，不做视频生成。
- skills/：任务方法；prompts/：版本化提示词。
- workflows/runner.py：编排、输出校验、候选与有限修复；API/store 负责幂等和版本事务。
- context/assembly.py：有长度预算的上下文与来源摘录，不自动保存长期记忆。
- memory/lifecycle.py：失效沿来源消息→上下文→任务→衍生回复传播，不直接修改剧本。
- tests/：unit、api、e2e；evals/：50 个固定创作案例与质量量表。
- data/：本地运行数据，Git 忽略。

照片：`backend/photo_api.py`、`photo_schemas.py` 管理独立项目；`workflows/photo.py` 分别编排 Prompt 与图生任务；`tools/photo_model.py` 管理通用 Base64 和明确选择的阿里云官方 URL 图片协议，独立 Key/开关/用途批准。URL 下载不得携带 Key；须限制官方主机、解析地址、重定向、大小和解码。`frontend/src/features/photos/` 为独立工作区。`scripts/photo_backup.py` 处理包含照片文件的完整 ZIP 备份。

照片 Prompt 操作不能隐式调用图片模型；直接输入 Prompt 生图不应调用文字模型。图片区分项目来源与直接输入，保持实际文本和版本快照。Pillow 仅验证图片字节可解码；不将离线占位图标为真实照片。新增照片验收见 docs/photo-validation.md。

前后端职责由各子 agent 独立承担，测试成员独立验收。共享契约和其他成员目录的修改由主 agent 协调。普通聊天只产生消息或候选；正式剧本变更需要用户应用且基础版本一致。

## 测试要求

必须验证时间覆盖 [0,N)、版本冲突、刷新持久化、导出解析、取消和重复请求、项目记忆隔离、确认前不注入、删除传播以及费用批准拦截。

真实 GUI 验证完整创作与对话/记忆流程、连续切换至少 20 次、错误恢复、键盘和 200% 缩放。离线 fixture、真实模型和外部视频效果分别报告。

权威命令：`.venv/bin/python -m pytest tests/unit tests/api -q`；前端目录 `pnpm build`；fixture服务下 `.venv/bin/python evals/runner.py --base-url http://127.0.0.1:8000`。浏览器命令和环境见 docs/validation.md。

## 依赖策略

使用项目虚拟环境、requirements.lock、frontend/pnpm-lock.yaml。Python 3.11+，Node 22.13+，pnpm 11.25.0。新增依赖说明用途并核验许可证，选择兼容稳定版本。没有明确需求时不引入向量库、消息队列或重型 Agent 框架。不要读取其他项目密钥；.env.example 只允许空值或假值，.env 不入 Git。付费调用需用户批准，配置 Key 本身不构成授权。

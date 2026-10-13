# 映序 · AIGC 视频编剧工作台

本地单用户 Web 应用。输入简短介绍，讨论和确认故事，生成可编辑的逐秒剧本与连续分镜 Prompt，导出给你选择的视频模型。包含项目对话、用户档案、可确认记忆、版本恢复和外部效果反馈。

默认 **离线示例**：确定性样例验证软件流程，不代表真实 AI 创作质量。真实文本模型由你配置和批准；本项目不调用视频生成服务。

## 照片创作：两个独立功能

顶层切换到“照片创作”。照片项目与视频项目分别保存：

- **Prompt 编写**：简介扩写为主体、场景、构图、光线、镜头、风格等可编辑字段，候选应用后可确认、复制或导出，不自动生成图片。
- **直接生成照片**：可使用已确认的项目 Prompt，也可直接粘贴已有 Prompt，确认后生成，无需先调用 Prompt 编写。图片保存实际文字、来源、模型、尺寸和版本，支持预览、下载与历史。

两类服务及批准分别管理。默认文字为示例，默认图片为醒目标注的离线占位图（非 AI 照片）。真实生图须配置独立的 `IMAGE_API_KEY`、`IMAGE_BASE_URL`、`IMAGE_MODEL`、`IMAGE_MODE=openai-compatible`、`PAID_IMAGE_CALLS_ENABLED=true`，再在照片设置中批准图片用途。文本 Key 和视频批准不能代替图片授权。

首版图片接口支持 `/images/generations` Base64 输出 PNG/JPEG/WebP，`response_format=auto` 省略旧参数。URL-only 供应商暂不支持。每次一张，没有自动重试；取消不保证供应商免计费。设置更改需要重新批准。

详见[照片模块说明](docs/photo-module.md)、[照片接口](docs/photo-api-contract.md)与[照片验收](docs/photo-validation.md)。

## 环境与启动

Python 3.11+、Node.js 22.13+、pnpm 11.25.0。已在 Python 3.12、Node 24.19.0 验证。Python 使用项目虚拟环境；版本固定在 `requirements.lock` 和 `frontend/pnpm-lock.yaml`。

```sh
git clone https://github.com/zhenglianglala-wq/aigc_manuscript.git
cd aigc_manuscript
bash scripts/setup.sh
.venv/bin/python scripts/dev.py
```

工作台：[http://127.0.0.1:5173](http://127.0.0.1:5173)，API 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。`Ctrl+C` 结束前后端。端口被占用时：

```sh
.venv/bin/python scripts/dev.py --api-port 8100 --web-port 8173
```

Codex 自带环境时脚本可定位 bundled Python/Node/pnpm；其他机器使用系统安装的工具。也可以分别运行后端 `.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`，以及前端 `cd frontend && pnpm dev`。代理默认连接 8000，自定义时设置 `VITE_API_TARGET=http://127.0.0.1:8100`。不要通过 `file://` 打开前端。

## 核心流程

1. 创建项目：简介 1–6000 字符、时长 5–120 秒、画幅和可选硬约束。
2. 故事扩写：先生成候选，查看后应用，再确认故事。
3. 生成分镜：应用时间轴候选，选择分镜，编辑每一秒。
4. 局部重写：选择范围与锁定字段，查看差异后应用。
5. 检查：验证时间覆盖、引用、Prompt 同步和显式文本约束；视觉连续与故事质量需人工判断。
6. 导出 JSON / Markdown / CSV。JSON 保留项目、版本与规则元数据，CSV 包含逐秒和分镜 Prompt。
7. 参考与反馈：登记公开案例及外部生成视频、实际 Prompt、模型和人工评价。

逐秒内容用于创作编辑，连续分镜 Prompt 是主要生成输入。时间区间为 `[start,end)`。目标视频模型是否准确执行时序必须在外部生成后检查；通用/动作优先规则不是供应商效果承诺。

## 对话、用户与记忆

- 用户档案：名称、语言、默认时长/画幅/风格；本地单用户无需登录。
- 项目对话：引用某秒/分镜，讨论剧情；普通聊天不改变正式剧本。
- 修改候选：用户应用才创建正式版本；旧版本候选返回冲突，避免覆盖新编辑。
- 记忆：确认后生效；项目记忆仅本项目，用户偏好可跨项目。可查看来源、修改后重新确认、停用和删除。
- 上下文：近期消息及可追溯摘录；运行记录可查看使用的记忆/版本/引用。摘录是有长度限制的节选，不是模型理解摘要。
- 删除记忆排除其来源在后续上下文中复用；原对话单独管理。备份可能仍含旧对话与旧记忆。

本地 `owner_id` 是归属字段，不是多人身份认证。服务默认绑定本机，当前不适合直接开放到公网。

## 真实文本模型与费用批准

`.env.example` 仅含空值/说明，可提交 Git；`.env` 初始只有空值变量且被忽略。真实密钥仅在本机 `.env` 或系统环境配置，前端只看到是否已配置。

```dotenv
LLM_API_KEY=在本机填写你的真实密钥
LLM_BASE_URL=https://你的兼容服务/v1
LLM_MODEL=你的模型名称
LLM_MODE=openai-compatible
DATA_DIR=
PAID_CALLS_ENABLED=true
```

重启后在设置检查运行模式、地址和模型；设置页保存的非敏感配置优先于环境默认值。仅支持明确的 `/chat/completions` JSON 协议，服务须支持 `response_format: json_object`。真实供应商尚未验收。

Key 和开关不代表批准。设置页为具体项目批准调用，指定次数、预算/未知费用接受和有效期，再在工作台选中批准。每次调用及重试消耗次数，撤销或过期停止新调用。模型或价格等配置变化需重新批准。缺少价格或 usage 显示未知；已知费用按配置估算，以供应商账单为准。取消不保证上游停止计费。

离线示例不需要 Key、批准或付费开关。开发和自动测试不会调用真实收费服务。

## 测试与评估

```sh
.venv/bin/python -m pytest tests/unit tests/api -q
cd frontend && pnpm build
# fixture 后端运行时，从项目根目录执行
.venv/bin/python evals/runner.py --base-url http://127.0.0.1:8000
```

50 个固定案例检测程序和输出结构；真实模型人工质量与外部视频效果未验证。完整浏览器脚本、依赖和证据见 [validation.md](docs/validation.md)。

Prompt 调优见 [prompt-quality.md](docs/prompt-quality.md)。从两个已导出结果准备匿名对比表：

```sh
.venv/bin/python scripts/compare_prompts.py baseline.json workflow.json --out evals/results/blind
```

要求分镜数量与时间范围一致；CSV 给评审，`answer-key.json` 保密直至评分结束。工具不调用模型，也不自动判胜。不能仅凭提示词长度或样例分数宣称优于其他模型。

## 数据、备份与恢复

默认 `data/studio.sqlite3`，SQLite 事务保存版本化 JSON 实体与项目索引。`data/`、运行日志、`.env`、测试证据和评估结果不入 Git。不要将真实对话加入公开测试材料。

设置页可创建并下载数据库备份，不包含 `.env` 密钥。命令行方式：

```sh
.venv/bin/python scripts/backup.py backup data/backups/manual.sqlite3
.venv/bin/python scripts/backup.py validate data/backups/manual.sqlite3
# 停止服务，核对备份后恢复
.venv/bin/python scripts/backup.py restore data/backups/manual.sqlite3 --confirm
```

恢复先验证 Schema、完整性和引用再替换。原数据保存在 `studio.pre-restore.sqlite3`；该文件已存在时需先移开。备份会恢复当时的记忆，确认范围后再操作。WAL 文件存在时拒绝替换，先正常停服。

存在照片资产时，设置页的完整备份自动生成 ZIP，包含数据库和引用的照片文件。有照片时不要只保存数据库；使用完整备份命令：

```sh
.venv/bin/python scripts/photo_backup.py backup data/backups/full.zip
.venv/bin/python scripts/photo_backup.py validate data/backups/full.zip
# 先正常停止服务，再恢复
.venv/bin/python scripts/photo_backup.py restore data/backups/full.zip --confirm
```

ZIP 校验照片引用、SHA256 与安全路径，恢复前验证到临时目录；原数据库和照片保存在 `data/pre-restore/`。当前完整备份上限 512 MiB；不包含密钥或以前的备份文件。备份含本地对话、记忆和图片，请按个人数据管理。

## 文档与代码

- [完整计划书](docs/project-plan.md)
- [接口契约](docs/api-contract.md)
- [开发团队](docs/agent-team.md)
- [代码、测试与依赖规则](agent.md)
- [验收报告](docs/validation.md)

页面 `frontend/`；API/存储 `backend/`；角色 `agents/`；外部能力 `tools/`；方法 `skills/`；流程 `workflows/`；模板 `prompts/`；上下文 `context/`；记忆规则 `memory/`；程序检查 `tests/`；任务评估 `evals/`。

常见问题：依赖缺失先运行 setup；连接失败核对端口；409 保留草稿后刷新比较；导出阻断先修复检查项；真实调用被拦截核对 Key、开关、模型、批准和预算。离线内容较模板化是预期限制，真实创作质量需要模型和人工评估。

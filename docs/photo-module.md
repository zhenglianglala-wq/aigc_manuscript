# 照片创作模块

新增独立照片项目，与视频项目分别保存。照片创作分为两个主动操作：

1. **照片 Prompt**：输入简短简介，扩写主体、环境、构图、光线、色彩、氛围和细节。结果先为候选；可以编辑、确认、复制或导出，不自动调用图片服务。
2. **直接生成照片**：用户可以选择确认过的项目 Prompt，也可直接粘贴并确认已有 Prompt，明确点击生成，调用独立图片服务。后者无需文字模型，不修改结构化 Prompt。保存图片、实际文字、来源、项目/Prompt 版本、模型、尺寸与运行记录，支持预览和下载。

照片 Prompt 共用文本服务配置，但照片 Prompt 审批与视频审批分别绑定。图片服务使用独立 IMAGE_* 环境变量与付费开关，文本 Key 不自动用作图片 Key。配置 Key 或服务地址不是费用批准。

## 数据边界

照片项目、版本、候选、任务、图片及批准均关联照片项目 ID。修改 Prompt 取消确认；已经生成的图片保持原版本来源。旧任务不能覆盖新的 Prompt。图片生成每次一张、没有自动重试；不明确的上游失败可能已经计费，重试由用户主动决定。

默认 Prompt 为确定性离线示例，默认图片为明确标注的占位图；它们不代表真实模型质量或摄影效果。原始简介及实际参数保留，可检查是否满足要求。

## 兼容接口

图片服务使用 `POST /images/generations`，首版接收 `data[0].b64_json`，验证字节后存为本地图片。不自动下载供应商返回的外部 URL；URL-only 服务返回明确不支持说明。

`response_format=auto` 表示省略该请求字段；兼容服务确实支持时可选择 `b64_json`。GPT image 模型默认返回 Base64，且不支持旧的 response_format 参数。参数依据：[OpenAI 图片生成 API 文档](https://developers.openai.com/api/reference/resources/images/methods/generate?site_locale=en)（2026-10-13 核验）。

尺寸提供 `1024x1024`、`1536x1024`、`1024x1536`。服务必须支持所选尺寸；不会冒充已经验证所有兼容供应商。图生成费用按用户配置估算，供应商未提供 usage 时 Token 显示未知，不填零。

## 实施与验收

后端：backend/photo_api.py 与 photo_schemas.py；图像接口 tools/photo_model.py；流程 workflows/photo.py；离线样例 agents/photo_fixture.py。前端：独立照片工作区，延续 Apple 风格和键盘/缩放/实色降级。

契约见 photo-api-contract.md。测试覆盖两功能分离、不同审批用途、版本冲突、取消、重复请求、图片字节验证和下载、刷新历史以及原视频回归。真实服务及图像质量需要配置并获得费用批准后验证；当前开发没有获得付费调用授权。

完整备份：存在照片时 `/api/backups` 返回含数据库与资产的 ZIP，无照片仍返回 SQLite。CLI 见 README；`scripts/photo_backup.py` 校验引用/哈希/路径，临时验证后恢复，旧数据保留。单独 SQLite 只包含元数据，不能恢复照片文件。

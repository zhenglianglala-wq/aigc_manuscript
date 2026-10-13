# 映序前端

React、TypeScript、Vite；依赖锁定在 `pnpm-lock.yaml`。仅 esbuild 的依赖构建脚本被允许。

环境要求：Node.js >=22.13.0、pnpm 11.25.0；本次构建使用 bundled Node.js 24.19.0。

```sh
pnpm install --frozen-lockfile
pnpm dev
pnpm build
```

默认 http://127.0.0.1:5173，`/api` 和 `/health` 代理到 http://127.0.0.1:8000。
测试后端地址可通过 `VITE_API_TARGET=http://127.0.0.1:8100 pnpm dev --port 8173` 改变；不要向 `VITE_*` 放置密钥。

开发服务每 500ms 轮询源码变更，避免 Codex 多代理共享文件写入时文件事件丢失、浏览器仍收到旧模块。配置变更需重启开发服务；此设置不影响生产构建。

## 代码边界

- `src/app/App.tsx`：工作台布局、项目作用域、API 编排与任务轮询；使用后端版本号和任务列表。
- `src/api/client.ts`：HTTP、稳定错误映射与附件下载；不访问模型厂商。
- `src/domain/types.ts`：API 数据类型、时间码及状态文案。
- `src/features/brief/`：创建表单、输入草稿。
- `src/features/storyboard/`：连续分镜、逐秒编辑与冲突草稿。
- `src/features/revisions/`：候选前后对比与显式应用。
- `src/features/chat/`：项目对话、引用、消息操作。
- `src/features/memory/`：范围、来源、确认、编辑、停用与删除。
- `src/features/profile/`：档案、非敏感模型设置、批准与备份。
- `src/components/`：语义控件；`src/styles/`：明暗、材质、动效与响应式样式。
- 项目导航、故事编辑、检查、运行记录、导出与参考反馈目前由 App 编排，空 feature 目录保留为拆分位置。

本地浏览器只缓存 UI 偏好及未提交草稿；正式项目、消息、记忆与任务从后端重读。密钥仅在后端环境配置。离线 fixture 始终显示为确定性示例，所有生成结果先进入候选。

`build` 包含 TypeScript 检查；真实跨层浏览器测试位于项目根 `tests/e2e/`。构建通过不代表浏览器或真实模型验收通过。

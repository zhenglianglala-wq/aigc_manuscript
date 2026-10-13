# 验收与复现

## 隔离与执行

所有自动测试使用临时 SQLite、合成输入和明确 fixture 模型，不读取其他项目 `.env`，不调用收费 API。API 测试 `create_app(data_dir=tmp_path)`；GUI 启动独立后端 `127.0.0.1:8100`，前端 `5173`，`VITE_API_TARGET=http://127.0.0.1:8100`。同一浏览器只有测试成员操作。

```sh
.venv/bin/pytest tests/unit tests/api -q
.venv/bin/python evals/build_cases.py
.venv/bin/python evals/runner.py --base-url http://127.0.0.1:8100 --output evals/results/fixture.json
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/aigc-playwright node tests/e2e/workbench.cjs
# CSS short-viewport regression, using the synthetic project preserved by workbench.cjs
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/aigc-playwright node tests/e2e/layout.cjs
```

浏览器命令需要已有 Playwright 和 Chromium；本次使用 bundled Playwright 与临时目录中的 Chromium。脚本支持 `PLAYWRIGHT_MODULE` 指定包路径、`CHROMIUM_EXECUTABLE` 指定可执行路径、`STUDIO_URL` 指定前端地址、`STUDIO_API_URL` 指定后端。运行前确认后端 `/api/settings/model` 的 mode 为 fixture。脚本拒绝非 fixture。沙箱限制 Chromium 启动时，本次经自动审批使用沙箱外隔离浏览器。Vite 使用500ms轮询以防多agent文件事件漏更新，GUI预检实际服务模块含稳定可访问名。

## 必须闭环

真实用户入口创建→扩写候选→应用→故事确认→分镜候选→应用→编辑某秒→保存→刷新重读→导出落盘解析；聊天仅产生回复/候选；记忆未确认不注入、确认后注入、项目隔离、编辑重新确认、删除传播；过期候选和双标签旧版本不得覆盖正式内容。

重复请求幂等、取消后迟到结果不得应用、重启任务 interrupted、上游失败恢复、权限与费用拦截均需程序断言。恢复备份先在临时目录重开并核对引用，损坏备份不覆盖原文件。无真实调用批准时仅测试授权门和本地 HTTP 模拟上游，不代表厂商协议/计费验收。

连续切项目/镜头至少20次、加载中切换、重复展开关闭、键盘焦点、200%缩放、窄窗口、减少动态与实色降级均需实际操作。截图必须打开检查遮挡、文字、焦点和错误反馈；截图不证明流畅。下载必须保存并解析，对照当前正式版本。

## 证据与报告

运行产物 `tests/artifacts/`、`evals/results/` 为本地证据，不加入公开源码。报告记录源码版本、环境、工具、步骤、项目/版本、状态、服务/模型/数据保真度和证据文件。使用 passed / failed / blocked / skipped；已知缺陷计入 failed。HTTP 200 或构建成功不能代替用户流程。

50固定例通过只证明 fixture 结构与程序行为，真实模型人工量表、外部视频效果、真实供应商取消/usage/成本均为另行批准后的未验证项。缺失价格或Token显示未知，取消不得自动计零费用。

## 当前结果

2026-10-13 最终执行：Python 3.12、真实本地 FastAPI/SQLite、Vite/React、Playwright Chromium headless，数据为合成、模型为 fixture。付费服务未调用。

| 验收 | 结果与证据 |
| --- | --- |
| unit/API | **31 passed**，1个anyio依赖弃用提示；涵盖取消迟到保护、幂等、版本、来源衍生链失效、删除Run/候选脱敏、审批配置绑定、有限结构修复与逐次成本未知、SQLite备份恢复/损坏保护、真实导出包装的盲评CLI |
| 固定创作案例 | **50 passed / 0 failed**；`evals/results/fixture.json`，包含源码与案例SHA256。原constraints-06保留：fixture禁止指令混入画面的缺陷修复后通过 |
| 浏览器主流程 | **10个阶段通过**，无未处理pageErrors；`tests/artifacts/run-1791854082388/`。实际创建/候选确认/人物描述保存/分镜/逐秒编辑刷新/JSON Markdown CSV下载解析；模拟poll503后仅重试GET、生成POST=1；503草稿保留重试与双标签409；聊天草稿清空、记忆确认删除；项目与镜头各20次快切；键盘、实色/减少动态、暗色；删除项目后API404 |
| 视觉复核 | 已打开8张主流程截图；200%等效短视口发现项目列表文字重叠，**原始失败证据保留**。CSS最小修复后仅针对200%/窄屏/宽屏复验，几何断言及3张截图人工复核通过：`tests/artifacts/layout-1791854200970/` |

最终摘要：`tests/artifacts/gui-report.json`；原始运行报告保留视觉失败，最新摘要关联定向修复报告。没有修改测试预期或换掉固定失败输入来掩盖缺陷。

证据绑定（完整模块哈希在JSON报告中）：

- `backend/main.py`: `a1a14622b6ee7e5ff2aac0b34958cf1493f752d58097c72a14bf1023d221d551`
- `frontend/src/app/App.tsx`: `19b4bf2f429458ba61fcd6c9e719119e6a7c6789cb99345d96356c7fc42b6b80`
- 最终CSS：`2e4529959d8eb6a26007ab812b1625fc9b9fe07af3bdce0514d4b0ccf29c9bb9`
- 50案例：`606a56dec8ca65b80858abc48c01bb1e0d6cb50353ad6fa70dc58fcb4bdd5351`

仍未验证：真实模型叙事质量/供应商usage计费/外部视频生成效果、其他浏览器/系统、完整读屏测试、动效性能采样。200%验收采用720×500 CSS视口加2倍CDP pageScale的重排等效模拟与实际键盘操作，未操作浏览器菜单缩放；不能宣称所有平台的真实200%设置已验证。逐秒约束与禁止内容检查含字面规则，不能代替语义人工审查。

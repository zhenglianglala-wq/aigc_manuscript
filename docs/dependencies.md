# 依赖用途与选择

版本以 requirements.lock、frontend/pnpm-lock.yaml 为准。以下许可证来自本机安装包元数据，未复用参考仓库代码。

| 直接依赖 | 用途 | 许可证 |
| --- | --- | --- |
| FastAPI | 本地 HTTP API 和接口文档 | MIT |
| Pydantic | 输入与模型结构校验 | MIT |
| Uvicorn | ASGI 进程 | BSD-3-Clause |
| HTTPX | 有界超时的兼容模型 HTTP 调用、离线模拟 | BSD-3-Clause |
| python-dotenv | 仅后端加载本机配置 | BSD-3-Clause |
| pytest | 独立程序测试 | MIT |
| Pillow 11.2.1 | PNG/JPEG/WebP 像素解码验证，拒绝头部有效但无法预览的图片 | MIT-CMU |
| React / React DOM | 前端组件与状态 | MIT |
| Vite / React 插件 | 开发代理及构建 | MIT |
| TypeScript | 前端契约类型检查 | Apache-2.0 |

SQLite 使用 Python 标准库；无需另装数据库服务。未引入向量库、Redis、队列或重型 Agent 框架。开发包管理器 pnpm 11.25.0 要求 Node 22.13+，本机使用 Node 24.19.0。只允许 esbuild 的依赖构建脚本。

浏览器验收使用环境已有 Playwright；测试 Chromium 下载到临时路径，不是用户产品运行依赖。其包路径通过 PLAYWRIGHT_MODULE 指定，浏览器位置通过 PLAYWRIGHT_BROWSERS_PATH 指定。

新增依赖须说明实际需求、版本兼容与许可证，并更新锁文件。不将 node_modules、虚拟环境、包缓存或浏览器二进制提交 Git。

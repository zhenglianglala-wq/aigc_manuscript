# 照片模块独立验收

照片与视频项目、文本扩写与图片生成分别验收。默认fixture；协议使用HTTPX MockTransport，不打开外部连接，不使用真实密钥，不调用收费服务。

```sh
.venv/bin/python -m pytest -q
.venv/bin/python evals/runner.py --base-url http://127.0.0.1:8100 --output evals/results/fixture.json
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/aigc-playwright node tests/e2e/photos.cjs
```

浏览器沿用已有bundled Playwright，可通过PLAYWRIGHT_MODULE/STUDIO_URL/STUDIO_API_URL配置。服务采用独立DATA_DIR，文本与图片mode均fixture，两个Key为空，PAID_CALLS_ENABLED与PAID_IMAGE_CALLS_ENABLED=false。照片GUI启动前检查服务配置，无真实模型模式不误称实测。

## 覆盖边界

- Prompt生成只走文本接口、产生未应用候选，不发起图片请求；视频批准不能用于照片，照片prompt批准不能授权image。
- 生成图片必须已确认项目Prompt，或独立direct_prompt并显式confirm_direct_prompt。直接输入保持原文，不调用LLM、不创建Project.prompt、不增加项目版本；asset保留来源和冻结快照。
- 图片独立Key/开关/目的批准；配置变更导致批准失效；次数、预算与未知费用独立记录。每次n=1，不自动重试。
- 图片协议/mock：有效Base64 PNG真实落盘并下载；URL-only、坏Base64、SVG冒充、截断PNG、正确CRC但不能解码的IDAT明确失败，不写资产。文件签名不代替像素解码。
- 候选应用、人工修改后取消确认；任务版本冻结、幂等、取消后迟到结果不保存；项目切换/删除隔离；fixture SVG用户文字不得变成script元素。
- 完整ZIP备份包含DB与图片；在全新目录恢复并重开API，核对元数据、下载字节与checksum。缺媒体、校验失败、路径穿越、损坏ZIP均拒绝且原数据库不被部分覆盖。

GUI真实流程：创建照片项目→丰富Prompt候选→应用→编辑→保存确认→独立图片按钮→非AI占位图预览与真实下载XML解析→刷新历史→编辑取消确认但历史快照保留→第二项目跳过Prompt编写直接粘贴确认生成→切换隔离→窄窗口截图→视频工作台输入smoke。

## 当前状态

2026-10-13：完整 pytest 53 passed（原31项、照片22项）；视频50固定离线案例50 passed/0 failed；前端生产构建及依赖检查通过。照片浏览器5阶段passed，零pageerrors。主agent另验证20次连续切换、200%缩放无横向溢出；实际查看全部5张流程截图和缩放截图，未发现遮挡。

本地证据：tests/artifacts/photos-1791896857988/photo-gui-report.json（含源码SHA256、步骤和截图）；tests/artifacts/photo-extra.cjs 与 photo-200.png 为额外切换/缩放检查。运行数据和截图不提交Git。

fixture占位图、Mock图片协议、真实生成照片效果分别记录；真实图片模型质量、计费及取消供应商请求未获批准，未运行。

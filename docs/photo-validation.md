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

## 2026-10-14：阿里云限定 URL 协议回归

独立执行 `.venv/bin/python -m pytest tests/api/test_aliyun_images.py -q`：**22 passed / 0 failed**，1个既有anyio依赖弃用提示。HTTP与DNS全部使用本地模拟；本轮没有真实服务请求、密钥读取或付费调用。

新增协议通过图片配置 `response_format=aliyun_url` 选择，图片调用批准绑定此配置；通用auto/b64_json仍拒绝URL返回。

- 模拟官方OSS签名URL下载：只连接预先验证的public IP；Host与TLS SNI保持官方域名，签名查询保留；GET不带Authorization、Proxy-Authorization或图片Key。下载PNG真实保存、预览/下载字节一致。
- 任意域名、本地地址、HTTP、URL凭证、伪域名后缀、未批准OSS bucket、非443端口和file URL在GET前拒绝。
- 即使官方域名，DNS包含任一私网/本地/链路本地地址也拒绝；固定validated IP避免后续DNS重绑定。
- 302重定向不跟随；Content-Length超限、实际流式超限、CRC合法但不能解码的PNG失败，不保存资产，不自动重试。
- 任意API地址/路径不能启用阿里云协议；已有批准在response_format改变后拒绝调用。

此轮只证明本地协议处理与下载边界，不代表阿里云账户、实际生成质量、官方费用或线上网络已验证。后续主控如执行用户明确批准的真实图片调用，应单独记录范围、次数、预算和实际结果，不能并入Mock通过数。完整pytest与前端构建由主控集成执行。

此轮核心源码SHA256：`tools/photo_model.py` 为 `8f957cd9b0a7c99ff6432133e22a412acb3dd5e7923cd614f769f9d1775647c4`；测试文件为 `9794082bb5cc8e2f74c6b63b2bfb49607e26bdd12ded1791440adc67bcc15114`。

## 2026-10-14：真实单次调用与结果下载恢复修正

主控在用户明确批准的一次真实图片调用中，生成API返回结果，但本地下载被当时的固定域名名单拒绝。没有保存图片资产、未取得可供检查的本地照片，不能报告生图成功或照片效果通过。估算费用为0.1元，供应商可能已经计费，实际账单未核验；程序没有自动重试。旧实现没有保存原始签名URL，因此该次结果无法通过新恢复入口找回。新增生成调用须另获用户批准。

针对真实返回暴露的域名限制，新规则支持官方 `dashscope-{id}` bucket 的限定 `oss-cn-{region}.aliyuncs.com` 与 `oss-accelerate.aliyuncs.com` 形式，仍拒绝任意bucket、伪域名后缀、非HTTPS、凭证、非443、重定向与任何私网DNS地址。模型生成成功响应先写私有回执，再校验/下载；回执文件0600，不含图片Key，签名URL不返回API或备份下载。

新增恢复入口：`POST /api/photo-projects/{id}/runs/{original_run_id}/recover-image`，仅恢复有回执的失败/中断Aliyun结果下载，已取消任务拒绝。该操作不调用生成接口，不消耗新批准次数，沿用原始Prompt/模型/尺寸/版本快照；相同原任务的并发点击复用恢复任务，避免重复保存资产。原生成调用费用与恢复操作分开记录，网络传输费用不能因“0生成调用”被承诺为供应商账单绝对为零。

最终专项执行：`.venv/bin/python -m pytest tests/api/test_aliyun_images.py -q` **28 passed / 0 failed**，全部HTTP/DNS模拟，未额外调用真实服务。覆盖区域与加速域名、有效PNG下载、正确MIME后的实际大小限制/像素解码失败、私有回执权限及API/备份脱敏、关闭Key/开关并撤销批准后的GET-only恢复、原calls_used=1、原快照、不同幂等键并发复用、取消拒绝及删除项目清理回执。既有53项加当前28项共81项，由主控完成最终集成检查；前端新增恢复按钮的实际用户操作尚未由本测试成员执行，不据Mock报告GUI通过。

本轮SHA256：`tools/photo_model.py` 为 `47c3535bd52901a115253c14b782a9f78637420f98fc9ec57d8289ea7f73ca22`；`backend/photo_api.py` 为 `1a80101df18d8c767c8587d39fec9b8cf07f5499cab4d11c888c48596907ce71`；测试文件为 `1dcaaa4301bd9a3cf21d36bb7782536eac25de4435be0c2c9d358524405ca3e2`。

主控最终集成：完整pytest **81 passed**、前端生产构建通过。另进行只读GUI检查：阿里云配置选项正常，旧任务缺少回执时不显示恢复按钮；零pageerrors、无生成POST。主控已实际打开 `/private/tmp/aigc-aliyun-settings.png` 检查，未发现布局问题。该检查不包含有回执任务的恢复按钮端到端操作；新的付费生成批准仍待用户回复，本轮没有额外生成调用。

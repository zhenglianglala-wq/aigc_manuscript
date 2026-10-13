/* Real browser + real local services + explicitly synthetic fixture model. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const modulePath = process.env.PLAYWRIGHT_MODULE || '/Users/zhengliang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright';
const {chromium, request} = require(modulePath);
const {expect} = require(path.join(modulePath, 'test.js'));
const root = path.resolve(__dirname, '../..');
const artifactRoot = path.join(root, 'tests/artifacts');
const artifacts = path.join(artifactRoot, `run-${Date.now()}`); fs.mkdirSync(artifacts, {recursive:true});
const report = {service:'real', model:'fixture', data:'synthetic', steps:[], pageErrors:[], screenshots:[], started:new Date().toISOString()};
report.source_hashes={};
function fingerprint(dir) {for(const entry of fs.readdirSync(dir,{withFileTypes:true})) {const full=path.join(dir,entry.name);if(entry.isDirectory()&&entry.name!=='__pycache__')fingerprint(full);else if(entry.isFile()&&/\.(py|tsx?|css|json)$/.test(entry.name))report.source_hashes[path.relative(root,full)]=crypto.createHash('sha256').update(fs.readFileSync(full)).digest('hex');}}
for(const dir of ['frontend/src','backend','agents','context','memory','tools','workflows','prompts'])fingerprint(path.join(root,dir));
const url = process.env.STUDIO_URL || 'http://127.0.0.1:5173';
const apiUrl = process.env.STUDIO_API_URL || 'http://127.0.0.1:8100';
let page, browser, api;
async function step(name, fn) {
  try {await fn(); report.steps.push({name,status:'passed'}); console.log('PASS',name);}
  catch(error) {report.steps.push({name,status:'failed',error:String(error)}); throw error;}
}
async function capture(name) {await page.evaluate(()=>window.scrollTo(0,0));const filename=path.join(artifacts,`${name}.png`); await page.screenshot({path:filename,fullPage:true});report.screenshots.push({path:filename,visual_review:'pending'});}
async function getProject(id) {const response=await api.get(`/api/projects/${id}`); assert.equal(response.status(),200);return response.json();}
async function create(title, description) {
  await page.getByRole('button',{name:'＋ 创建项目',exact:true}).click();
  await page.getByLabel('简短介绍',{exact:false}).fill(description);
  await page.getByLabel('目标时长（秒）',{exact:true}).fill('15');
  await page.getByText('更多设定',{exact:true}).click();
  await page.getByLabel('项目名称',{exact:true}).fill(title);
  await page.getByRole('button',{name:'创建项目',exact:true}).click();
  await expect(page.locator('.toolbar-title strong')).toHaveText(title);
  return new URL(page.url()).searchParams.get('project');
}
async function main() {
 api=await request.newContext({baseURL:apiUrl});
 const settings=await (await api.get('/api/settings/model')).json();
 assert.equal(settings.mode,'fixture','Refusing non-fixture browser run');
 const served=await fetch(`${url}/src/components/UI.tsx`).then(r=>r.text());
 assert.ok(served.includes('aria-labelledby'),'Development server serves stale Field code: restart Vite before validation');
 report.served_field_sha256=crypto.createHash('sha256').update(served).digest('hex');
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE || chromium.executablePath()});
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
 page=await context.newPage();page.on('pageerror',err=>report.pageErrors.push(String(err)));
 await page.goto(url);
 let firstId, secondId, savedVersion;
 const nonce=Date.now();const firstTitle=`GUI故事甲${nonce}`,secondTitle=`GUI故事乙${nonce}`;
 await step('UI create and persisted brief',async()=>{
   firstId=await create(firstTitle,'一位雨夜邮差找到一封迟到的家书');
   assert.equal((await getProject(firstId)).brief.description,'一位雨夜邮差找到一封迟到的家书');
   await expect(page.getByText('离线示例：确定性演示内容',{exact:false})).toBeVisible();
 });
 await step('Expansion candidate requires apply and story confirmation',async()=>{
   let interrupted=false,posts=0;
   const countPost=req=>{if(req.method()==='POST'&&req.url().includes(`/api/projects/${firstId}/runs`))posts++;};page.on('request',countPost);
   const polling='**/api/runs/*';
   await page.route(polling,route=>{if(route.request().method()==='GET'&&!interrupted){interrupted=true;return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{code:'SIMULATED_POLL',message:'临时失败',retryable:true}})});}return route.continue();});
   await page.getByRole('button',{name:'故事扩写',exact:true}).click();
   await expect(page.getByText('暂时无法读取任务进度',{exact:false})).toBeVisible();
   await capture('poll-reconnect');
   await expect(page.getByRole('button',{name:'应用候选',exact:true})).toBeVisible();
   await page.unroute(polling);page.off('request',countPost);assert.equal(posts,1,'Polling retry must not resubmit a paid-capable task');
   assert.equal((await getProject(firstId)).document.story,null);
   await page.getByRole('button',{name:'应用候选',exact:true}).click();
   await expect(page.getByRole('button',{name:'确认故事',exact:true})).toBeVisible();
   await page.getByText('编辑人物与场景',{exact:true}).click();
   await page.getByRole('textbox',{name:'人物 1 固定描述',exact:true}).fill('邮差始终穿深蓝色风衣，胸前佩戴银色徽章');
   await page.getByRole('button',{name:'保存人物与场景',exact:true}).click();
   await page.getByRole('button',{name:'确认故事',exact:true}).click();
   await expect(page.getByRole('button',{name:'生成分镜',exact:true})).toBeVisible();
   assert.equal((await getProject(firstId)).document.story.confirmed,true);
 });
 await step('Timeline candidate, edit, save and refresh reread',async()=>{
   await page.getByRole('button',{name:'生成分镜',exact:true}).click();
   await expect(page.getByRole('button',{name:'应用候选',exact:true})).toBeVisible();
   assert.equal((await getProject(firstId)).document.beats.length,0);
   await page.getByRole('button',{name:'应用候选',exact:true}).click();
   await expect(page.getByRole('button',{name:'编辑镜头 1',exact:true})).toBeVisible();
   assert.ok((await getProject(firstId)).document.shots[0].prompt.includes('银色徽章'));
   await page.getByRole('button',{name:'编辑镜头 1',exact:true}).click();
   await page.locator('.beat-editor').getByLabel('画面',{exact:false}).fill('雨后信箱旁，邮差轻轻展开蓝色信纸');
   await page.getByRole('button',{name:'保存这一秒',exact:true}).click();
   await expect(page.getByRole('button',{name:'保存这一秒',exact:true})).toBeDisabled();
   const current=await getProject(firstId);savedVersion=current.current_revision;
   assert.equal(current.document.beats[0].visual,'雨后信箱旁，邮差轻轻展开蓝色信纸');
   assert.ok(current.document.shots[0].prompt.includes('蓝色信纸'));
   await page.reload();
   await page.getByRole('button',{name:'分镜',exact:true}).click();
   await page.getByRole('button',{name:'编辑镜头 1',exact:true}).click();
   await expect(page.locator('.beat-editor').getByLabel('画面',{exact:false})).toHaveValue('雨后信箱旁，邮差轻轻展开蓝色信纸');
   await capture('timeline-saved');
 });
 await step('All exports download to disk and parse current version',async()=>{
   await page.getByText('导出',{exact:true}).click();
   for(const format of ['JSON','MARKDOWN','CSV']) {
     const promise=page.waitForEvent('download');await page.getByRole('button',{name:format,exact:true}).click();
     const download=await promise;const dest=path.join(artifacts,download.suggestedFilename());await download.saveAs(dest);
     const text=fs.readFileSync(dest,'utf8');assert.ok(text.includes('蓝色信纸'));
     if(format==='JSON') {const data=JSON.parse(text);assert.equal(data.project.current_revision,savedVersion);assert.equal(data.project.document.beats.length,15);}
     if(format==='CSV') assert.ok(text.includes('start_second,end_second'));
   }
 });
 await step('Save failure preserves draft and retry succeeds',async()=>{
   await page.locator('.beat-editor').getByLabel('画面',{exact:false}).fill('失败后保留的绿色信封');
   const pattern=`**/api/projects/${firstId}/beats/0`;
   await page.route(pattern,route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{code:'SIMULATED_FAILURE',message:'测试服务暂时不可用',retryable:true}})}));
   await page.getByRole('button',{name:'保存这一秒',exact:true}).click();
   await expect(page.getByRole('alert')).toContainText('测试服务暂时不可用');
   await expect(page.locator('.beat-editor').getByLabel('画面',{exact:false})).toHaveValue('失败后保留的绿色信封');
   assert.equal((await getProject(firstId)).document.beats[0].visual,'雨后信箱旁，邮差轻轻展开蓝色信纸');
   await capture('save-failure-draft');
   await page.unroute(pattern);
   await page.getByRole('button',{name:'保存这一秒',exact:true}).click();
   await expect(page.getByRole('button',{name:'保存这一秒',exact:true})).toBeDisabled();
   assert.equal((await getProject(firstId)).document.beats[0].visual,'失败后保留的绿色信封');
   savedVersion=(await getProject(firstId)).current_revision;
 });
 await step('Two-tab conflict keeps unsaved draft and saved remote version',async()=>{
   const other=await context.newPage();other.on('pageerror',err=>report.pageErrors.push(String(err)));
   await other.goto(`${url}/?project=${firstId}`);
   await other.getByRole('button',{name:'分镜',exact:true}).click();
   await other.getByRole('button',{name:'编辑镜头 1',exact:true}).click();
   await other.locator('.beat-editor').getByLabel('画面',{exact:false}).fill('第二标签保存的白色信封');
   await other.getByRole('button',{name:'保存这一秒',exact:true}).click();
   await expect(other.getByRole('button',{name:'保存这一秒',exact:true})).toBeDisabled();
   await page.locator('.beat-editor').getByLabel('画面',{exact:false}).fill('第一标签冲突草稿');
   await page.getByRole('button',{name:'保存这一秒',exact:true}).click();
   await expect(page.getByRole('alert')).toContainText('版本');
   await expect(page.locator('.beat-editor').getByLabel('画面',{exact:false})).toHaveValue('第一标签冲突草稿');
   assert.equal((await getProject(firstId)).document.beats[0].visual,'第二标签保存的白色信封');
   await capture('version-conflict-draft');
   await page.getByRole('button',{name:'刷新',exact:true}).click();
   await page.getByRole('button',{name:'恢复当前内容',exact:true}).click();
   await expect(page.locator('.beat-editor').getByLabel('画面',{exact:false})).toHaveValue('第二标签保存的白色信封');
   savedVersion=(await getProject(firstId)).current_revision;
   await other.close();
 });
 await step('Chat and memory candidate confirmation deletion',async()=>{
   await page.locator('.inspector').getByRole('button',{name:'对话',exact:true}).click();
   await page.getByRole('textbox',{name:'你的想法',exact:true}).fill('所有镜头保持蓝色信纸');
   await page.getByRole('button',{name:'发送',exact:true}).click();
   await expect(page.locator('.message.assistant')).toHaveCount(1);
   await expect(page.getByRole('textbox',{name:'你的想法',exact:true})).toHaveValue('');
   assert.equal((await getProject(firstId)).current_revision,savedVersion);
   await page.locator('.message.user').getByRole('button',{name:'提取记忆候选',exact:true}).click();
   await expect(page.getByRole('button',{name:'确认记忆',exact:true})).toBeVisible();
   const memories=await (await api.get(`/api/memories?project_id=${firstId}`)).json();assert.equal(memories[0].status,'candidate');
   await page.getByRole('button',{name:'确认记忆',exact:true}).click();
   await expect(page.locator('.memory-card').getByText('已确认',{exact:true})).toBeVisible();
   const confirmed=await (await api.get(`/api/memories?project_id=${firstId}`)).json();assert.equal(confirmed[0].status,'confirmed');
   await page.getByRole('button',{name:'删除记忆',exact:true}).click();
   const dialog=page.getByRole('dialog');await expect(dialog).toBeVisible();
   await dialog.getByRole('button',{name:'取消',exact:true}).press('Tab');
   await expect(dialog.getByRole('button',{name:'确认',exact:true})).toBeFocused();
   await dialog.getByRole('button',{name:'确认',exact:true}).click();
   await expect(page.locator('.memory-card')).toHaveCount(0);
   await page.getByRole('textbox',{name:'你的想法',exact:true}).fill('请解释当前故事');await page.getByRole('button',{name:'发送',exact:true}).click();
   await expect(page.locator('.message.assistant')).toHaveCount(2);
   const runs=await (await api.get(`/api/projects/${firstId}/runs`)).json();
   const latest=runs.filter(r=>r.kind==='chat').at(-1);
   const snapshot=await (await api.get(`/api/runs/${latest.id}/context`)).json();assert.ok(!snapshot.memory_ids.includes(confirmed[0].id));
   await capture('chat-memory');
 });
 await step('20 fast project and shot switches preserve last intent',async()=>{
   secondId=await create(secondTitle,'清晨车站的重逢');
   const nav=page.getByRole('navigation',{name:'项目列表'});
   for(let i=0;i<20;i++) await nav.getByRole('button',{name:new RegExp(i%2===0?firstTitle:secondTitle)}).click();
   await expect(page.locator('.toolbar-title strong')).toHaveText(secondTitle);
   assert.equal(new URL(page.url()).searchParams.get('project'),secondId);
   await nav.getByRole('button',{name:new RegExp(firstTitle)}).click();
   await expect(page.locator('.toolbar-title strong')).toHaveText(firstTitle);
   await page.getByRole('button',{name:'分镜',exact:true}).click();
   await expect(page.getByRole('button',{name:'编辑镜头 3',exact:true})).toBeVisible();
   for(let i=0;i<20;i++) await page.getByRole('button',{name:`编辑镜头 ${i%3+1}`,exact:true}).click();
   await expect(page.locator('.inspector-heading h2')).toHaveText('分镜 2');
 });
 await step('Keyboard, 200% zoom, narrow and reduced solid material',async()=>{
   await page.getByRole('button',{name:'⚙ 设置',exact:true}).click();
   await page.getByLabel('使用实色材质，减少透明度',{exact:true}).check();
   await page.getByLabel('减少动态效果',{exact:true}).check();
   await page.emulateMedia({reducedMotion:'reduce'});
   // Reflow-equivalent 200% emulation; not a claim about OS/browser menu zoom.
   await page.setViewportSize({width:720,height:500});
   const cdp=await context.newCDPSession(page);await cdp.send('Emulation.setPageScaleFactor',{pageScaleFactor:2});
   await page.getByLabel('减少动态效果',{exact:true}).focus();await page.keyboard.press('Space');await page.keyboard.press('Space');
   await expect(page.getByLabel('减少动态效果',{exact:true})).toBeChecked();
   await capture('zoom-200-solid-reduced');
   await cdp.send('Emulation.setPageScaleFactor',{pageScaleFactor:1});
   await page.setViewportSize({width:640,height:900});
   await page.getByRole('navigation',{name:'项目列表'}).getByRole('button',{name:new RegExp(firstTitle)}).click();
   await page.getByRole('button',{name:'分镜',exact:true}).click();
   await expect(page.getByRole('button',{name:'编辑镜头 1',exact:true})).toBeVisible();
   await page.getByRole('button',{name:'编辑镜头 1',exact:true}).focus();
   await page.keyboard.press('Enter');await expect(page.locator('.beat-editor').getByLabel('画面',{exact:false})).toBeVisible();
   await capture('narrow-solid-reduced');
   await page.setViewportSize({width:1440,height:1000});
   await page.getByRole('button',{name:'切换深色主题',exact:true}).click();
   await page.getByRole('button',{name:'编辑镜头 2',exact:true}).click();
   await expect(page.locator('.inspector-heading h2')).toHaveText('分镜 2');
   await capture('dark-solid-reduced');
 });
 await step('Delete project confirms and removes persisted project',async()=>{
   await page.getByRole('navigation',{name:'项目列表'}).getByRole('button',{name:new RegExp(secondTitle)}).click();
   await expect(page.locator('.toolbar-title strong')).toHaveText(secondTitle);
   await page.getByRole('button',{name:'版本',exact:true}).click();
   await page.getByRole('button',{name:'删除项目',exact:true}).click();
   await page.getByRole('dialog').getByRole('button',{name:'确认',exact:true}).click();
   await expect(page.getByRole('navigation',{name:'项目列表'}).getByRole('button',{name:new RegExp(secondTitle)})).toHaveCount(0);
   assert.equal((await api.get(`/api/projects/${secondId}`)).status(),404);
 });
 assert.deepEqual(report.pageErrors,[],'Unhandled browser errors');
 report.status='passed';
 // Preserve synthetic projects for visual review; API corpus runner deletes its own cases.
 report.project_ids=[firstId,secondId];
}
main().catch(async error=>{report.status='failed';report.error=String(error);console.error(error);if(page)await capture('failure').catch(()=>{});process.exitCode=1;}).finally(async()=>{const output=JSON.stringify(report,null,2);fs.writeFileSync(path.join(artifacts,'gui-report.json'),output);fs.writeFileSync(path.join(artifactRoot,'gui-report.json'),output);if(browser)await browser.close();if(api)await api.dispose();});

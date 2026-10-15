/* Real local API/database, simulated external image vendor; no billable calls. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const pkg=process.env.PLAYWRIGHT_MODULE||'/Users/zhengliang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright';
const {chromium,request}=require(pkg),{expect}=require(path.join(pkg,'test.js'));
const web=process.env.STUDIO_URL||'http://127.0.0.1:8173',base=process.env.STUDIO_API_URL||'http://127.0.0.1:8120';
const dir=path.resolve(__dirname,'../artifacts','platform-'+Date.now());fs.mkdirSync(dir,{recursive:true});
const report={application:'real local frontend/backend/SQLite',vendor:'simulated HTTPX transport',paid_calls:0,steps:[],screenshots:[],page_errors:[]};
let browser,page,api,pid;
const json=async url=>(await api.get(url)).json();
const count=async()=>(await json('/api/test/metrics')).generation_requests.length;
const approvals=async()=>(await json('/api/photo-approvals')).filter(a=>a.photo_project_id===pid);
const stage=async(name,fn)=>{await fn();report.steps.push({name,status:'passed'});console.log('PASS '+name)};
const shot=async name=>{const file=path.join(dir,name+'.png');await page.screenshot({path:file,fullPage:true});report.screenshots.push(file)};
(async()=>{
 api=await request.newContext({baseURL:base});assert.equal((await json('/api/test/metrics')).simulation,true,'Must use isolated simulated-vendor server');
 await api.patch('/api/photo-settings/image',{data:{mode:'openai-compatible',base_url:'https://image-model.invalid/v1',model:'simulated-image',response_format:'b64_json',estimated_price_per_image:.1}});
 const initial=await count();browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true});page.on('pageerror',e=>report.page_errors.push(String(e)));
 await page.goto(web+'/?photo_view=image');await expect(page.getByTestId('photo-workspace')).toBeVisible();
 await stage('Create through UI and use brief as direct prompt',async()=>{
  await page.getByRole('button',{name:'＋ 创建照片项目',exact:true}).click();await page.getByRole('textbox',{name:'照片简短介绍',exact:true}).fill('窗边一只橘猫和白色陶瓷杯，柔和自然光');await page.getByRole('button',{name:'创建照片项目',exact:true}).click();await expect(page.getByRole('button',{name:'② 直接生成照片',exact:true})).toBeVisible();pid=new URL(page.url()).searchParams.get('photo_project');assert.ok(pid);
  await page.getByRole('button',{name:'② 直接生成照片',exact:true}).click();await page.getByRole('button',{name:'使用照片简介',exact:true}).click();await expect(page.getByRole('textbox',{name:'直接输入的图片 Prompt',exact:true})).toHaveValue('窗边一只橘猫和白色陶瓷杯，柔和自然光');await page.getByRole('checkbox',{name:'我确认使用这段直接输入的 Prompt',exact:true}).check();
 });
 await stage('Cancel fee dialog creates neither approval nor generation',async()=>{
  const before=(await approvals()).length;await page.getByRole('button',{name:'生成一张照片',exact:true}).click();await expect(page.getByRole('dialog',{name:'确认生成一张照片'})).toBeVisible();await shot('fee-confirmation');await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toHaveCount(0);assert.equal((await approvals()).length,before);assert.equal(await count(),initial);
 });
 let asset;
 await stage('Inline consent double click yields one run and preview',async()=>{
  await page.getByRole('button',{name:'生成一张照片',exact:true}).click();await page.getByRole('button',{name:'批准并生成1张',exact:true}).dblclick();await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.locator('.photo-image-preview')).toBeVisible();await expect.poll(()=>count()).toBe(initial+1);
  asset=(await json(`/api/photo-projects/${pid}/assets`))[0];await expect.poll(()=>page.locator('.photo-image-preview').evaluate(i=>i.complete&&i.naturalWidth===1024)).toBe(true);const ap=await approvals();assert.equal(ap.length,1);assert.equal(ap[0].max_calls,1);assert.equal(ap[0].calls_used,1);assert.equal(ap[0].budget,.1);assert.equal((await json(`/api/photo-projects/${pid}`)).prompt,null);await shot('generated-preview');
 });
 await stage('Download real bytes then reopen deep-linked history',async()=>{
  const event=page.waitForEvent('download');await page.getByRole('button',{name:'下载当前图片',exact:true}).click();const dl=await event,file=path.join(dir,dl.suggestedFilename());await dl.saveAs(file);assert.deepEqual(fs.readFileSync(file),await(await api.get(asset.download_url)).body());
  const fresh=await browser.newPage();await fresh.goto(`${web}/?photo_project=${pid}&photo_view=image`);await expect(fresh.getByTestId('photo-workspace')).toBeVisible();await expect(fresh.locator('.photo-image-preview')).toBeVisible();await fresh.close();await page.reload();await expect(page.locator('.photo-image-preview')).toBeVisible();await page.getByRole('button',{name:'照片历史',exact:true}).click();await expect(page.locator('.photo-image-preview')).toBeVisible();await page.getByRole('button',{name:'② 直接生成照片',exact:true}).click();
  await page.getByRole('checkbox',{name:'我确认使用这段直接输入的 Prompt',exact:true}).check();
 });
 await stage('Unknown fee requires explicit acceptance',async()=>{
  await api.patch('/api/photo-settings/image',{data:{estimated_price_per_image:null}});await page.getByRole('button',{name:'刷新照片',exact:true}).click();await page.getByRole('button',{name:'生成一张照片',exact:true}).click();const approve=page.getByRole('button',{name:'批准并生成1张',exact:true});await expect(approve).toBeDisabled();await page.getByRole('checkbox',{name:'我接受本次费用未知，最多生成 1 张',exact:true}).check();await expect(approve).toBeEnabled();await page.getByRole('button',{name:'取消生成',exact:true}).click();assert.equal(await count(),initial+1);
 });
 await stage('Model changed after review cannot consume approval',async()=>{
  await api.patch('/api/photo-settings/image',{data:{estimated_price_per_image:.1}});await page.getByRole('button',{name:'刷新照片',exact:true}).click();await page.getByRole('button',{name:'生成一张照片',exact:true}).click();const before=(await approvals()).length;await api.patch('/api/photo-settings/image',{data:{model:'changed-after-review'}});await page.getByRole('button',{name:'批准并生成1张',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('图片配置已改变');assert.equal((await approvals()).length,before);assert.equal(await count(),initial+1);await page.getByRole('button',{name:'关闭确认',exact:true}).click();
 });
 await stage('Vendor failure leaves old preview and never retries automatically',async()=>{
  await api.patch('/api/photo-settings/image',{data:{model:'simulated-failure'}});await page.getByRole('button',{name:'刷新照片',exact:true}).click();await page.getByRole('button',{name:'生成一张照片',exact:true}).click();await page.getByRole('button',{name:'批准并生成1张',exact:true}).click();await expect.poll(async()=>{const runs=await json(`/api/photo-projects/${pid}/runs`);return runs.some(r=>r.status==='failed')}).toBe(true);await expect(page.getByRole('button',{name:'查看失败任务与下载恢复',exact:true})).toBeVisible();assert.equal(await count(),initial+2);assert.equal((await json(`/api/photo-projects/${pid}/assets`)).length,1);await expect(page.locator('.photo-image-preview')).toHaveAttribute('src',asset.preview_url);
 });
 await stage('20 navigation changes, 200 percent dialog, keyboard cancel',async()=>{
  for(let i=0;i<10;i++){await page.getByRole('button',{name:'照片历史',exact:true}).click();await page.getByRole('button',{name:'② 直接生成照片',exact:true}).click();}
  await page.evaluate(()=>document.documentElement.style.zoom='2');await page.getByRole('button',{name:'生成一张照片',exact:true}).click();await shot('zoom-fee-dialog');assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth+2));await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toHaveCount(0);assert.equal(await count(),initial+2);assert.deepEqual(report.page_errors,[]);
 });
 report.status='passed';
})().catch(e=>{report.status='failed';report.error=String(e.stack||e);console.error(e);process.exitCode=1}).finally(async()=>{fs.writeFileSync(path.join(dir,'report.json'),JSON.stringify(report,null,2));console.log('Evidence: '+dir);await browser?.close();await api?.dispose()});

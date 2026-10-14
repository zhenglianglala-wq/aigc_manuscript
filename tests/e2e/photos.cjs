/* Real local UI, fixture photos only. Text and image actions remain separate. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process');
const pkg=process.env.PLAYWRIGHT_MODULE||'/Users/zhengliang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright';
const {chromium,request}=require(pkg),{expect}=require(path.join(pkg,'test.js'));
const root=path.resolve(__dirname,'../..'),dir=path.join(root,'tests/artifacts',`photos-${Date.now()}`);fs.mkdirSync(dir,{recursive:true});
const web=process.env.STUDIO_URL||'http://127.0.0.1:5173',apiUrl=process.env.STUDIO_API_URL||'http://127.0.0.1:8100';
const report={service:'real',model:'fixture',data:'synthetic',steps:[],screenshots:[],page_errors:[],status:'pending',source_hashes:{}};
for(const file of ['backend/main.py','backend/photo_api.py','backend/photo_schemas.py','tools/photo_model.py','workflows/photo.py','frontend/src/app/App.tsx','frontend/src/features/photos/PhotoWorkspace.tsx','frontend/src/features/photos/PhotoPromptEditor.tsx','frontend/src/styles/app.css','frontend/src/styles/photos.css']){const full=path.join(root,file);if(fs.existsSync(full))report.source_hashes[file]=crypto.createHash('sha256').update(fs.readFileSync(full)).digest('hex');}
let browser,page,api,pid;
async function stage(name,fn){try{await fn();report.steps.push({name,status:'passed'});console.log('PASS',name)}catch(e){report.steps.push({name,status:'failed',error:String(e)});throw e}}
async function snapshot(name){await page.evaluate(()=>scrollTo(0,0));const file=path.join(dir,name+'.png');await page.screenshot({path:file,fullPage:true});report.screenshots.push({path:file,visual_review:'pending'})}
async function project(){return (await api.get(`/api/photo-projects/${pid}`)).json()}
async function assets(){return (await api.get(`/api/photo-projects/${pid}/assets`)).json()}
(async()=>{
 api=await request.newContext({baseURL:apiUrl});
 assert.equal((await(await api.get('/api/photo-settings/image')).json()).mode,'fixture');assert.equal((await(await api.get('/api/settings/model')).json()).mode,'fixture');
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||chromium.executablePath()});
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});page=await context.newPage();page.on('pageerror',e=>report.page_errors.push(String(e)));
 await page.goto(web);await page.getByRole('button',{name:'照片创作',exact:true}).click();await expect(page.getByTestId('photo-workspace')).toBeVisible();
 const title='GUI照片'+Date.now();
 await stage('Create independent photo project',async()=>{
  await page.getByRole('button',{name:'＋ 创建照片项目',exact:true}).click();await page.getByRole('textbox',{name:'照片简短介绍',exact:true}).fill('雨后的窗边，白色陶瓷杯与一支小雏菊');
  await page.getByText('更多照片设定',{exact:true}).click();await page.getByRole('textbox',{name:'照片项目名称',exact:true}).fill(title);
  await page.getByRole('button',{name:'创建照片项目',exact:true}).click();await expect(page.locator('.toolbar-title strong')).toHaveText(title);
  pid=new URL(page.url()).searchParams.get('photo_project');assert.ok(pid);assert.equal((await project()).prompt,null);
 });
 await stage('Prompt-only generation candidate, edit and confirm',async()=>{
  await page.getByRole('button',{name:'丰富照片 Prompt',exact:true}).click();await expect(page.getByRole('button',{name:'应用照片候选',exact:true})).toBeVisible();
  assert.equal((await project()).prompt,null);assert.equal((await assets()).length,0);
  await page.getByRole('button',{name:'应用照片候选',exact:true}).click();await expect(page.getByRole('textbox',{name:'主体',exact:true})).toBeVisible();
  await page.getByRole('textbox',{name:'主体',exact:true}).fill('橘色陶瓷杯，杯沿凝结微小水珠');await page.getByRole('button',{name:'保存照片 Prompt',exact:true}).click();
  await expect(page.getByRole('button',{name:'保存照片 Prompt',exact:true})).toBeDisabled();assert.equal((await project()).prompt.confirmed,false);
  await page.getByRole('button',{name:'确认照片 Prompt',exact:true}).click();await expect(page.getByRole('button',{name:'前往直接生成照片',exact:true})).toBeVisible();assert.equal((await project()).prompt.confirmed,true);
  assert.ok((await project()).prompt.compiled_prompt.includes('橘色陶瓷杯'));assert.equal((await assets()).length,0);await snapshot('prompt-confirmed');
 });
 let generated;
 await stage('Separate image action renders labelled fixture and downloads actual SVG',async()=>{
  await page.getByRole('button',{name:'前往直接生成照片',exact:true}).click();await page.getByRole('button',{name:'生成离线占位图',exact:true}).click();
  const image=page.getByRole('img',{name:'离线占位图，非 AI 照片',exact:true});await expect(image).toBeVisible();
  await expect.poll(()=>image.evaluate(img=>img.complete&&img.naturalWidth>0&&img.naturalHeight>0)).toBe(true);generated=(await assets())[0];assert.equal(generated.mode,'fixture');
  const promise=page.waitForEvent('download');await page.getByRole('button',{name:'下载当前图片',exact:true}).click();const download=await promise;const file=path.join(dir,download.suggestedFilename());await download.saveAs(file);
  const parsed=spawnSync(path.join(root,'.venv/bin/python'),['-c','import sys,xml.etree.ElementTree as E;r=E.parse(sys.argv[1]).getroot();assert r.tag.endswith("svg");assert not any(n.tag.split("}")[-1]=="script" for n in r.iter())',file]);assert.equal(parsed.status,0,String(parsed.stderr));
  const downloaded=fs.readFileSync(file);assert.deepEqual(downloaded,await(await api.get(generated.download_url)).body());await snapshot('fixture-preview');
 });
 await stage('Refresh photo history and preserve prompt snapshot after edits',async()=>{
  await page.reload();await expect(page.getByTestId('photo-workspace')).toBeVisible();await page.getByRole('button',{name:'照片历史',exact:true}).click();
  await expect(page.getByRole('img',{name:'离线占位图，非 AI 照片',exact:true})).toBeVisible();assert.equal((await assets())[0].id,generated.id);
  await page.getByRole('button',{name:'① Prompt 编写',exact:true}).click();await page.getByRole('textbox',{name:'主体',exact:true}).fill('修改后蓝色陶瓷杯');await page.getByRole('button',{name:'保存照片 Prompt',exact:true}).click();await expect(page.getByRole('button',{name:'保存照片 Prompt',exact:true})).toBeDisabled();
  assert.equal((await project()).prompt.confirmed,false);await page.getByRole('button',{name:'② 直接生成照片',exact:true}).click();await expect(page.getByRole('button',{name:'生成离线占位图',exact:true})).toBeDisabled();assert.equal((await assets())[0].prompt_text,generated.prompt_text);await snapshot('history-frozen');
 });
 await stage('Project switch isolation, narrow layout and video workspace smoke',async()=>{
  await page.getByRole('button',{name:'＋ 创建照片项目',exact:true}).click();await page.getByRole('textbox',{name:'照片简短介绍',exact:true}).fill('另一张独立照片');await page.getByRole('button',{name:'创建照片项目',exact:true}).click();
  await expect(page.locator('.toolbar-title strong')).toHaveText('另一张独立照片');await page.getByRole('button',{name:'② 直接生成照片',exact:true}).click();await expect(page.getByRole('img',{name:'离线占位图，非 AI 照片',exact:true})).toHaveCount(0);
  const directId=new URL(page.url()).searchParams.get('photo_project'),direct='  一盏台灯照亮打开的书本，低角度构图。  ';
  await page.getByRole('textbox',{name:'直接输入的图片 Prompt',exact:true}).fill(direct);await page.getByRole('checkbox',{name:'我确认使用这段直接输入的 Prompt',exact:true}).check();
  await page.getByRole('button',{name:'生成离线占位图',exact:true}).click();await expect(page.getByRole('img',{name:'离线占位图，非 AI 照片',exact:true})).toBeVisible();
  const directProject=await(await api.get(`/api/photo-projects/${directId}`)).json();assert.equal(directProject.prompt,null);assert.equal(directProject.current_revision,1);
  const directAssets=await(await api.get(`/api/photo-projects/${directId}/assets`)).json();assert.equal(directAssets[0].prompt_source,'direct');assert.equal(directAssets[0].prompt_text,direct);assert.equal(directAssets[0].prompt_revision,null);await snapshot('direct-prompt-image');
  await page.getByRole('navigation',{name:'照片项目列表'}).getByRole('button',{name:new RegExp(title)}).click();await page.getByRole('button',{name:'照片历史',exact:true}).click();await expect(page.getByRole('img',{name:'离线占位图，非 AI 照片',exact:true})).toBeVisible();
  await page.setViewportSize({width:640,height:900});await snapshot('narrow-photo-history');await page.setViewportSize({width:1440,height:1000});
  await page.getByRole('button',{name:'视频剧本',exact:true}).click();await expect(page.getByRole('button',{name:'＋ 创建项目',exact:true})).toBeVisible();await page.getByRole('button',{name:'＋ 创建项目',exact:true}).click();await expect(page.getByRole('textbox',{name:'简短介绍',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'照片创作',exact:true}).click();await expect(page.getByTestId('photo-workspace')).toBeVisible();
 });
 assert.deepEqual(report.page_errors,[]);report.status='passed';report.photo_project_id=pid;
})().catch(async e=>{report.status='failed';report.error=String(e);console.error(e);if(page)await snapshot('failure').catch(()=>{});process.exitCode=1}).finally(async()=>{fs.writeFileSync(path.join(dir,'photo-gui-report.json'),JSON.stringify(report,null,2));console.log('REPORT',dir);if(browser)await browser.close();if(api)await api.dispose()});

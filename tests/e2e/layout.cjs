/* Targeted regression for the short-viewport sidebar overlap found by visual review. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const pkg=process.env.PLAYWRIGHT_MODULE||'/Users/zhengliang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright';
const {chromium}=require(pkg),{expect}=require(path.join(pkg,'test.js'));
const root=path.resolve(__dirname,'../..'),artifacts=path.join(root,'tests/artifacts',`layout-${Date.now()}`);fs.mkdirSync(artifacts,{recursive:true});
const prior=JSON.parse(fs.readFileSync(path.join(root,'tests/artifacts/gui-report.json')));
const url=process.env.STUDIO_URL||'http://127.0.0.1:5173';
const report={scope:'CSS layout regression only',model:'fixture',screenshots:[],status:'pending',source_css_sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'frontend/src/styles/app.css'))).digest('hex')};
let browser,page;
(async()=>{
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||chromium.executablePath()});
 const context=await browser.newContext({viewport:{width:720,height:500}});page=await context.newPage();
 await page.goto(`${url}/?project=${prior.project_ids[0]}`);
 await page.getByRole('button',{name:'⚙ 设置',exact:true}).click();
 await page.getByLabel('使用实色材质，减少透明度',{exact:true}).check();await page.getByLabel('减少动态效果',{exact:true}).check();
 await page.emulateMedia({reducedMotion:'reduce'});
 const cdp=await context.newCDPSession(page);await cdp.send('Emulation.setPageScaleFactor',{pageScaleFactor:2});
 // Read-only geometry: detect text extending outside compressed project buttons.
 const overlaps=await page.locator('.project-list button').evaluateAll(buttons=>buttons.flatMap(button=>{const outer=button.getBoundingClientRect();const title=button.querySelector('strong').getBoundingClientRect();return title.bottom>outer.bottom+1?[{title:button.innerText,title_bottom:title.bottom,button_bottom:outer.bottom}]:[]}));
 assert.deepEqual(overlaps,[],'Project titles must fit their buttons instead of overlapping adjacent entries');
 const save=async(name)=>{await page.evaluate(()=>scrollTo(0,0));const dest=path.join(artifacts,name+'.png');await page.screenshot({path:dest,fullPage:true});report.screenshots.push({path:dest,visual_review:'pending'});};
 await save('zoom-200-fixed');
 await cdp.send('Emulation.setPageScaleFactor',{pageScaleFactor:1});await page.setViewportSize({width:640,height:900});
 await page.getByRole('navigation',{name:'项目列表'}).getByRole('button',{name:/GUI故事甲/}).first().click();
 await page.getByRole('button',{name:'分镜',exact:true}).click();await page.getByRole('button',{name:'编辑镜头 1',exact:true}).click();
 await expect(page.locator('.beat-editor').getByRole('textbox',{name:'画面',exact:true})).toBeVisible();await save('narrow-fixed');
 await page.setViewportSize({width:1440,height:1000});await save('wide-fixed');report.status='passed';
})().catch(async err=>{report.status='failed';report.error=String(err);if(page)await page.screenshot({path:path.join(artifacts,'failure.png'),fullPage:true}).catch(()=>{});process.exitCode=1;}).finally(async()=>{fs.writeFileSync(path.join(artifacts,'layout-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));if(browser)await browser.close();});

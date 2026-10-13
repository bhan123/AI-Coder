const {chromium}=require('C:/Users/36997/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  for(const width of [1440,390]) {
   const page=await browser.newPage({viewport:{width,height:900}});
   const errors=[];page.on('pageerror',e=>errors.push(String(e)));
   const response=await page.goto('https://hermes-content-review.taild890b1.ts.net:10000/#review-center',{waitUntil:'networkidle',timeout:45000});
   await page.getByRole('heading',{name:'复盘与诊断',exact:true}).waitFor();
   const nav=page.getByRole('navigation',{name:'页面导航'});
   assert.equal(await nav.getByRole('link',{name:'复盘与诊断',exact:true}).isVisible(),true);
   await nav.getByRole('link',{name:'每日信号',exact:true}).click();
   assert.equal(await page.getByRole('heading',{name:'复盘与诊断',exact:true}).count(),0);
   await page.screenshot({path:__dirname+`/navigation-${width}-homepage.png`});
   await nav.getByRole('link',{name:'复盘与诊断',exact:true}).click();
   await page.getByRole('heading',{name:'复盘与诊断',exact:true}).waitFor();
   await page.screenshot({path:__dirname+`/navigation-${width}-review.png`});
   console.log(JSON.stringify({width,status:response.status(),url:page.url(),title:await page.title(),scripts:await page.locator('script[src]').evaluateAll(els=>els.map(e=>e.src)),headers:response.headers(),errors}));
   await page.close();
  }
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});

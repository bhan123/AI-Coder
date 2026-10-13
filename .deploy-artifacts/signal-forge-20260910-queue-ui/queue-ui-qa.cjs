const { chromium } = require('C:/Users/36997/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const target = 'https://hermes-content-review.taild890b1.ts.net:10000/';
const candidate = process.argv.includes('--candidate');
const out = __dirname;

(async () => {
  const browser = await chromium.launch({ channel:'msedge', headless:true });
  const evidence = { target, candidate, browser:'Edge / Playwright; Browser plugin not available', runs:[] };
  try {
    for (const viewport of [{width:1440,height:1000},{width:390,height:844}]) {
      const context = await browser.newContext({viewport});
      const page = await context.newPage();
      const errors=[];
      page.on('pageerror', error => errors.push(String(error)));
      page.on('console', message => {if(message.type()==='error') errors.push(message.text());});
      if (candidate) {
        await page.route(target, route => route.fulfill({path:path.join(out,'dist','index.html'),contentType:'text/html'}));
        await page.route('**/assets/*', async route => {
          const name = path.posix.basename(new URL(route.request().url()).pathname);
          assert.ok(/^[a-zA-Z0-9_.-]+$/.test(name));
          await route.fulfill({path:path.join(out,'dist','assets',name),contentType:name.endsWith('.css')?'text/css':'application/javascript'});
        });
        await page.route('**/api/review/collection/jobs?*', async route => {
          const p=new URL(route.request().url()).searchParams;
          const offset=Number(p.get('offset')||0), limit=Number(p.get('limit')||25), code=p.get('code');
          const all=Array.from({length:32},(_,i)=>({trade_date:'2026-09-04',code:String(i+1).padStart(6,'0'),provider:'qa-only-not-product',status:'completed',attempt_count:2,availability:'completed',ready_to_collect:false,next_eligible_at:null,last_error_type:null,updated_at:'2026-09-04T16:30:00+08:00',evidence_id:'qa-evidence'}));
          const matches=all.filter(row=>(!code||row.code===code)&&(!p.get('status')||row.status===p.get('status')));
          const items=matches.slice(offset,offset+limit);
          await route.fulfill({json:{queue_status:'available',as_of:'2026-09-10T12:00:00+08:00',items,total:matches.length,counts_by_status:matches.length?{completed:matches.length}:{},offset,limit,next_offset:offset+items.length<matches.length?offset+items.length:null}});
        });
        await page.route('**/api/review/collection/attempts?*', async route => {
          const p=new URL(route.request().url()).searchParams;
          const key={trade_date:p.get('trade_date'),code:p.get('code'),provider:p.get('provider')};
          const items=[{...key,sequence:2,status:'completed',attempted_at:'2026-09-04T16:30:00+08:00',finished_at:'2026-09-04T16:30:01+08:00',evidence_id:'qa-evidence'}, {...key,sequence:1,status:'failed',attempted_at:'2026-09-04T16:00:00+08:00',finished_at:'2026-09-04T16:00:01+08:00',error_type:'Timeout'}];
          await route.fulfill({json:{queue_status:'available',items,total:2,offset:0,limit:25,next_offset:null,job:{...key,status:'completed',availability:'completed',evidence_id:'qa-evidence'}}});
        });
      }
      const response=await page.goto(target+'#review-center',{waitUntil:'domcontentloaded',timeout:45000});
      assert.equal(response.status(),200);
      assert.equal(await page.title(),'Signal Forge');
      await page.getByRole('heading',{name:'复盘与诊断',exact:true}).waitFor();
      const tab=page.getByRole('button',{name:'补采诊断',exact:true});
      assert.equal(await tab.count(),1,'Expected a collection diagnostics tab');
      await tab.click();
      await page.getByRole('heading',{name:'收盘补采诊断',exact:true}).waitFor();
      assert.equal(await page.getByLabel('复盘策略').isDisabled(),true);
      const expand=page.getByRole('button',{name:/查看 \d{6} 补采记录/}).first();
      await expand.waitFor({timeout:30000});
      const firstKey=await expand.getAttribute('aria-label');
      await expand.click();
      const detail=page.getByRole('region',{name:'采集尝试记录',exact:true});
      await detail.waitFor();
      await detail.getByText('尝试时间',{exact:true}).waitFor();
      await detail.scrollIntoViewIfNeeded();
      const bounds=await detail.boundingBox();
      assert.ok(bounds.width<=viewport.width+2,JSON.stringify(bounds));
      await page.screenshot({path:path.join(out,`${candidate?'candidate':'live'}-${viewport.width}-attempts.png`)});
      const next=page.getByRole('button',{name:'下一页任务',exact:true});
      assert.equal(await next.isDisabled(),false);
      await next.click();
      await page.getByText('第 2 页',{exact:true}).waitFor();
      await page.getByRole('button',{name:/查看 \d{6} 补采记录/}).first().waitFor();
      assert.notEqual(await page.getByRole('button',{name:/查看 \d{6} 补采记录/}).first().getAttribute('aria-label'),firstKey);
      assert.equal(await detail.count(),0);
      await page.getByLabel('补采股票代码').fill('001');
      await page.getByRole('button',{name:'筛选任务',exact:true}).click();
      await page.getByRole('alert').filter({hasText:'六位'}).waitFor();
      await page.getByLabel('补采股票代码').fill('999999');
      await page.getByRole('button',{name:'筛选任务',exact:true}).click();
      await page.getByText('当前筛选没有匹配任务，不代表所有复盘证据已经齐全。',{exact:true}).waitFor();
      await page.getByRole('button',{name:'重置任务筛选',exact:true}).click();
      await page.getByRole('button',{name:/查看 \d{6} 补采记录/}).first().waitFor();
      assert.equal(await page.getByLabel('补采股票代码').inputValue(),'');
      await page.getByText('第 1 页',{exact:true}).waitFor();
      await page.getByRole('heading',{name:'收盘补采诊断',exact:true}).scrollIntoViewIfNeeded();
      const layout=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
      assert.ok(layout.scroll<=layout.width+2,JSON.stringify(layout));
      assert.equal(await page.locator('vite-error-overlay').count(),0);
      assert.deepEqual(errors,[]);
      await page.screenshot({path:path.join(out,`${candidate?'candidate':'live'}-${viewport.width}-queue.png`)});
      evidence.runs.push({viewport,title:await page.title(),url:page.url(),layout,errors});
      await context.close();
    }
    await fs.writeFile(path.join(out,`${candidate?'candidate':'live'}-qa.json`),JSON.stringify(evidence,null,2));
    console.log(JSON.stringify(evidence));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});

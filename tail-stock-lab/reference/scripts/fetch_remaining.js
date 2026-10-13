// fetch_remaining.js
// 1) 抓剩余主帖 HTML
// 2) 翻页抓全部回帖
const fs = require('fs');
const path = require('path');
const https = require('https');

const COOKIE = 'sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%2219f366863251dcc-0deb240795ceb28-26061051-3686400-19f366863261d3e%22%7D; _HUPUSSOID=d36a2b97-0739-48bc-9db0-b9c9dc46db1d; u=18460199|aGlnaDNraWNr|aa90|78a02b89c1457c4b2bde9d2f0f1f4b49|6425f73e8418eaf4|aGlnaDNraWNr; ua=17854900; us=007e625022c23ffbefde1ae8f4a2f4fe4a70bf0c1c9adebf0389d0c437420e2496d6ea73dc994c115f5a8452b007a0d7b9bb9274ace034d73a8260649ac2b2e2; _CLT=00376064be821b71351c003dda774e37; csrfToken=47Ul73Qf1y4Lpr8seve88KGv; acw_tc=707c9f6817854898955322671eb852e9e0aea6e5a677391f9f4993d999da98; _c_WBKFRo=MEkcU7Zpzr5edkK9XizvjDNNTqb73gEnt27KySwc; HMACCOUNT=BD59DA3FC1BDF7B1; Hm_lvt_ac423772552f47d0bb3ae6d55e13262c=1785490164; Hm_lpvt_ac423772552f47d0bb3ae6d55e13262c=1785490164';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';
const CRAWL = 'C:/Users/36997/crawl';
const API = CRAWL + '/api';
const THREADS = CRAWL + '/threads';

function fetchUrl(url, opts={}) {
    return new Promise((resolve, reject) => {
        const u = new URL(url);
        const req = https.request({
            hostname: u.hostname,
            port: 443,
            path: u.pathname + u.search,
            method: opts.method || 'GET',
            rejectUnauthorized: false,
            headers: {
                'Cookie': COOKIE,
                'User-Agent': UA,
                'Origin': 'https://my.hupu.com',
                'Referer': 'https://my.hupu.com/95005319134322',
                ...(opts.headers || {})
            }
        }, (res) => {
            let data = '';
            res.on('data', c => data += c);
            res.on('end', () => resolve({ status: res.statusCode, body: data, headers: res.headers }));
        });
        req.on('error', reject);
        req.end();
    });
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function fetchAllReplies() {
    console.log('[replies] 开始翻页...');
    let maxTime = '9999999999';
    let page = 0;
    let allReplies = [];
    const seenPid = new Set();
    while (true) {
        page++;
        const url = `https://my.hupu.com/pcmapi/pc/space/v1/getReplyList?euid=95005319134322&maxTime=${maxTime}&page=1&pageSize=30`;
        const resp = await fetchUrl(url);
        if (resp.status !== 200) {
            console.log(`[replies] page=${page} HTTP ${resp.status}, stop.`);
            break;
        }
        let d;
        try { d = JSON.parse(resp.body); } catch (e) { console.log('[replies] JSON parse fail', resp.body.slice(0,200)); break; }
        if (d.code !== 1 || !d.data || !d.data.replyWithQuoteDtoList) {
            console.log(`[replies] page=${page} code=${d.code} msg=${d.msg}`);
            break;
        }
        const list = d.data.replyWithQuoteDtoList;
        if (list.length === 0) {
            console.log(`[replies] page=${page} 空, 结束`);
            break;
        }
        let newCount = 0;
        for (const r of list) {
            if (!seenPid.has(r.pid)) {
                seenPid.add(r.pid);
                allReplies.push(r);
                newCount++;
            }
        }
        const last = list[list.length - 1];
        console.log(`[replies] page=${page} +${newCount}/${list.length} (total=${allReplies.length}) lastPid=${last.pid} lastTime=${last.createTime} (${new Date(last.createTime*1000).toISOString()})`);
        if (list.length < 30) {
            console.log('[replies] less than 30, done.');
            break;
        }
        maxTime = String(last.createTime - 1);
        await sleep(400);
        if (page > 200) {
            console.log('[replies] safety break at 200 pages');
            break;
        }
    }
    fs.writeFileSync(`${API}/all_replies.json`, JSON.stringify({ count: allReplies.length, replies: allReplies }, null, 2));
    console.log(`[replies] saved ${allReplies.length} replies`);
    return allReplies;
}

async function fetchMissingThreadHTMLs() {
    console.log('[threads] 加载已有 tids + 全量 tids...');
    const allThreads = JSON.parse(fs.readFileSync(`${API}/all_threads.json`, 'utf8'));
    const tids = allThreads.threads.map(t => t.tid);
    console.log(`[threads] total ${tids.length}`);

    const outDir = THREADS;
    if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, {recursive: true});
    let fetched = 0, skipped = 0, failed = 0;
    for (const tid of tids) {
        const fp = `${outDir}/${tid}.html`;
        if (fs.existsSync(fp) && fs.statSync(fp).size > 5000) {
            skipped++;
            continue;
        }
        const url = `https://bbs.hupu.com/${tid}.html`;
        let resp;
        try {
            resp = await fetchUrl(url, { headers: { 'Referer': 'https://www.hupu.com/' }});
        } catch (e) {
            failed++; continue;
        }
        if (resp.status === 200 && resp.body.length > 5000) {
            fs.writeFileSync(fp, resp.body, 'utf8');
            fetched++;
        } else {
            failed++;
            console.log(`[threads] ${tid} HTTP ${resp.status} (${resp.body.length}B)`);
        }
        if ((fetched + skipped) % 10 === 0) console.log(`[threads] ${fetched} fetched, ${skipped} skipped, ${failed} failed`);
        await sleep(400);
    }
    console.log(`[threads] done. fetched=${fetched} skipped=${skipped} failed=${failed}`);
}

async function main() {
    await fetchAllReplies();
    await fetchMissingThreadHTMLs();
}

main().catch(e => { console.error(e); process.exit(1); });

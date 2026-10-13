// parse_threads_v2.js — 用 __NEXT_DATA__ 解析
const fs = require('fs');

const CRAWL = 'C:/Users/36997/crawl';
const THREADS_DIR = `${CRAWL}/threads`;
const API_DIR = `${CRAWL}/api`;
const OUT_FILE = `${CRAWL}/parsed_threads_v2.json`;

function readBOM(file) {
    return fs.readFileSync(file, 'utf8').replace(/^﻿/, '');
}

function htmlToText(html) {
    if (!html) return '';
    return html
        .replace(/<br\s*\/?>/g, '\n')
        .replace(/<\/p>/g, '\n')
        .replace(/<img[^>]*src="([^"]+)"[^>]*\/?>/g, '[$1]')
        .replace(/<a[^>]*href="([^"]+)"[^>]*>([^<]+)<\/a>/g, '$2 ($1)')
        .replace(/<[^>]+>/g, '')
        .replace(/&nbsp;/g, ' ')
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/\n\s*\n/g, '\n')
        .trim();
}

// JSON V3 doc 提取纯文本
function jsonV3ToText(jsonStr) {
    if (!jsonStr) return '';
    try {
        const j = typeof jsonStr === 'string' ? JSON.parse(jsonStr) : jsonStr;
        const doc = j.jsonV3 || j;
        if (!doc || !doc.content) return '';
        const parts = [];
        function walk(node) {
            if (node.type === 'text') parts.push(node.text || '');
            else if (node.content) for (const c of node.content) walk(c);
        }
        for (const p of doc.content) {
            walk(p);
            parts.push('\n');
        }
        return parts.join('').replace(/\n{3,}/g, '\n\n').trim();
    } catch (e) {
        return '';
    }
}

function parseThread(html) {
    // 找 __NEXT_DATA__
    const m = html.match(/<script id="__NEXT_DATA__" type="application\/json">([\s\S]+?)<\/script>/);
    if (!m) return null;
    let data;
    try { data = JSON.parse(m[1]); } catch (e) { return null; }
    const detail = data?.props?.pageProps?.detail;
    if (!detail) return null;

    const thread = detail.thread || {};
    const replies = detail.replies || {};
    const author = thread.author || {};

    // 主帖正文
    let mainText = '';
    if (thread.content) {
        // content 字段是 <p>...</p> HTML
        mainText = htmlToText(thread.content);
    }
    if (!mainText) mainText = jsonV3ToText(thread.format || thread.jsonV3);

    // 回帖列表
    const replyList = (replies.list || []).map(r => {
        let txt = htmlToText(r.content || '');
        if (!txt) txt = jsonV3ToText(r.format);
        return {
            pid: r.pid,
            floor: r.floor,
            user: r.user?.puname || '',
            puid: r.user?.puid,
            createTime: r.createdAt,
            formatTime: r.createdAtFormat,
            content: txt,
            likes: r.lights,
            replyReplyNum: r.replyReplyNum,
            isMy: r.user?.puid === 100213501
        };
    });

    return {
        tid: thread.tid,
        title: thread.title,
        author: author.puname,
        authorPuid: author.puid,
        authorLevel: author.level,
        createdAt: thread.createdAt,
        createdAtFormat: thread.createdAtFormat,
        forumName: thread.topic?.name,
        forumFid: thread.topic?.fid,
        visits: thread.read,
        repliesCount: replies.count || 0,
        lights: thread.lights,
        recommend: thread.recommend,
        mainText,
        replyList
    };
}

const threadMeta = JSON.parse(readBOM(`${API_DIR}/all_threads.json`));
const metaMap = new Map(threadMeta.threads.map(t => [String(t.tid), t]));

const outThreads = [];
let parsedOk = 0, missedStructure = 0, fileMissing = 0;
for (const meta of threadMeta.threads) {
    const fp = `${THREADS_DIR}/${meta.tid}.html`;
    if (!fs.existsSync(fp)) { fileMissing++; continue; }
    const html = readBOM(fp);
    const parsed = parseThread(html);
    if (!parsed) { missedStructure++; continue; }
    parsed.create_time = meta.create_time;
    parsed.fid = meta.fid;
    parsed.forum_name = meta.forum;
    outThreads.push(parsed);
    parsedOk++;
}

console.log(`Parsed ${parsedOk}, missed structure ${missedStructure}, missing file ${fileMissing}, total ${threadMeta.threads.length}`);

// 统计
const withText = outThreads.filter(t => t.mainText);
console.log(`Threads with main text: ${withText.length}`);

// 按内容长度分布
const lens = withText.map(t => t.mainText.length).sort((a,b)=>a-b);
console.log(`Min text len: ${lens[0]}, median: ${lens[Math.floor(lens.length/2)]}, max: ${lens[lens.length-1]}`);

// 该用户的回帖在主帖中的数量
let myRepliesInThreads = 0;
let threadsWithMyReplies = 0;
for (const t of outThreads) {
    const cnt = t.replyList.filter(r => r.puid === 100213501).length;
    if (cnt > 0) {
        myRepliesInThreads += cnt;
        threadsWithMyReplies++;
    }
}
console.log(`User replies in their own threads: ${myRepliesInThreads} (across ${threadsWithMyReplies} threads)`);

// 看一下"尾盘选股十连胜了"这个帖
const tail = outThreads.find(t => t.title && t.title.includes('尾盘选股十连胜'));
if (tail) {
    console.log('\n=== 尾盘选股十连胜了 ===');
    console.log('ID:', tail.tid);
    console.log('Time:', tail.createdAtFormat);
    console.log('Replies count:', tail.repliesCount);
    console.log('Main text:');
    console.log(tail.mainText.slice(0, 500));
    console.log('\nUser replies (myReplies):');
    const myReps = tail.replyList.filter(r => r.puid === 100213501);
    for (const r of myReps.slice(0, 10)) {
        console.log(`  - [${r.pid}] ${r.formatTime} ${r.content.slice(0, 120)}`);
    }
}

fs.writeFileSync(OUT_FILE, JSON.stringify({ count: outThreads.length, threads: outThreads }, null, 2));
console.log(`\nSaved ${OUT_FILE}`);

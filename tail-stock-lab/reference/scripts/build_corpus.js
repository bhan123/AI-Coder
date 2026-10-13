// build_corpus.js
const fs = require('fs');
const CRAWL = 'C:/Users/36997/crawl';
const API = `${CRAWL}/api`;

function readBOM(file) { return fs.readFileSync(file, 'utf8').replace(/^﻿/, ''); }

const threadsData = JSON.parse(readBOM(`${CRAWL}/parsed_threads_v3.json`));
const repliesData = JSON.parse(readBOM(`${API}/all_replies.json`));

// 收集所有 items
const items = [];

// 主帖
for (const t of threadsData.threads) {
    items.push({
        kind: 'main',
        tid: t.tid,
        title: t.title,
        time: t.createdAt,
        timeFmt: t.createdAtFormat,
        createTime: t.create_time,
        forum: t.forumName,
        fid: t.forumFid,
        content: t.mainText,
        isMyPost: String(t.authorPuid) === '100213501'
    });
}

// 自帖内回复
for (const t of threadsData.threads) {
    for (let i = 0; i < t.replyList.length; i++) {
        const r = t.replyList[i];
        if (!r.isUser) continue;
        items.push({
            kind: 'selfReply',
            tid: t.tid,
            title: t.title,
            time: r.time,
            content: r.content,
            isMyPost: false,
            puid: r.puid,
            parent_tid: t.tid
        });
    }
}

// getReplyList 中其他人主题下的回复（去重：先按 pid 收集，再排除已在自己主题内的）
const seenPid = new Set();
const myPidsInThreads = new Set();
for (const t of threadsData.threads) {
    for (const r of t.replyList) {
        if (r.puid) myPidsInThreads.add(r.pid);
    }
}
let otherReplies = 0;
let dupeSkipped = 0;
for (const r of repliesData.replies) {
    if (seenPid.has(r.pid)) continue;
    seenPid.add(r.pid);
    if (String(r.puid) !== '100213501') continue;
    if (myPidsInThreads.has(r.pid)) { dupeSkipped++; continue; }
    items.push({
        kind: 'repliedToOther',
        tid: r.tid,
        title: r.title,
        time: r.formatTime,
        timeUnix: r.createTime,
        content: r.content,
        topic: r.topicName,
        isMyPost: false,
        puid: r.puid,
        quote: r.quoteInfo ? { user: r.quoteInfo.username, text: r.quoteInfo.content } : null
    });
    otherReplies++;
}

// 推荐 (8) — 也包含
console.log(`主帖: ${threadsData.threads.length}`);
console.log(`自帖内回复: ${threadsData.threads.reduce((s,t)=>s+(t.myReplyCount||0),0)}`);
console.log(`回复他人主题: ${otherReplies} (跳过重复 pid: ${dupeSkipped})`);
console.log(`总 items: ${items.length}`);

// 关键词过滤
const keywords = ['尾盘', '选股', '打板', '板', '封板', '竞价', '低吸', '二板', '龙头', '接力', '埋伏', '次新', '涨停', '跌停', '断板', '反包', '建仓', '仓位', '止损', '盈亏比', '鱼塘', '鱼', '钓鱼', '鱼叉'];
function kwScore(text) {
    if (!text) return 0;
    let s = 0;
    for (const k of keywords) if (text.includes(k)) s++;
    return s;
}

// 找"尾盘选股"强相关 - 必须含"尾盘"和"选股"
const tailRelated = items.filter(it => {
    const title = it.title || '';
    const content = it.content || '';
    return /尾盘[\s\S]{0,30}选股|选股[\s\S]{0,30}尾盘/.test(title + content);
});

console.log(`\n强含"尾盘选股"的 items: ${tailRelated.length}`);
// 按时间排序
tailRelated.sort((a, b) => {
    const ta = a.createTime || a.timeUnix || 0;
    const tb = b.createTime || b.timeUnix || 0;
    return ta - tb;
});

// 输出前 20
console.log('\n=== 前 20 条"尾盘选股"相关 items (按时间正序) ===');
for (const it of tailRelated.slice(0, 20)) {
    const t = it.createTime ? new Date(it.createTime*1000).toISOString().slice(0,10) : (it.time || '');
    const title = (it.title||'').slice(0, 40);
    console.log(`[${it.kind}] ${t} [${it.tid}] ${title}`);
    console.log('  '+it.content.slice(0,200).replace(/\n/g,' '));
}

const corpus = {
    summary: {
        mainPosts: threadsData.threads.length,
        selfRepliesInOwnThreads: threadsData.threads.reduce((s,t)=>s+(t.myReplyCount||0),0),
        repliesToOtherThreads: otherReplies,
        total: items.length,
        tailRelatedCount: tailRelated.length
    },
    items,
    tailRelated
};
fs.writeFileSync(`${CRAWL}/corpus.json`, JSON.stringify(corpus, null, 2));
console.log(`\nSaved ${CRAWL}/corpus.json`);

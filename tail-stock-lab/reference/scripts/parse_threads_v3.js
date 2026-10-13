// parse_threads_v3.js — 最终版
const fs = require('fs');
const CRAWL = 'C:/Users/36997/crawl';
const THREADS_DIR = `${CRAWL}/threads`;
const API_DIR = `${CRAWL}/api`;
const OUT_FILE = `${CRAWL}/parsed_threads_v3.json`;

function readBOM(file) { return fs.readFileSync(file, 'utf8').replace(/^﻿/, ''); }
function htmlToText(html) {
    if (!html) return '';
    return html
        .replace(/<br\s*\/?>/g, '\n')
        .replace(/<\/p>/g, '\n')
        .replace(/<img[^>]*src="([^"]+)"[^>]*\/?>/g, '[$1]')
        .replace(/<a[^>]*href="([^"]+)"[^>]*>([^<]+)<\/a>/g, '$2 ($1)')
        .replace(/<[^>]+>/g, '')
        .replace(/&nbsp;/g, ' ')
        .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
        .replace(/\n\s*\n/g, '\n').trim();
}

function parseThread(html) {
    const m = html.match(/<script id="__NEXT_DATA__" type="application\/json">([\s\S]+?)<\/script>/);
    if (!m) return null;
    let data;
    try { data = JSON.parse(m[1]); } catch { return null; }
    const detail = data?.props?.pageProps?.detail;
    if (!detail) return null;
    const thread = detail.thread || {};
    const replies = (detail.replies?.list || []);
    const myReplies = [];

    const replyList = replies.map(r => {
        const isUser = String(r.author?.puid) === '100213501';
        const txt = htmlToText(r.content || '');
        if (isUser) myReplies.push({ pid: r.pid, time: r.createdAtFormat, content: txt });
        return {
            pid: r.pid,
            user: r.author?.puname || '',
            puid: r.author?.puid,
            isStarter: !!r.isStarter,
            isUser,
            time: r.createdAtFormat,
            content: txt,
            likes: r.allLightCount,
            replyNum: r.replyNum,
            location: r.location
        };
    });

    return {
        tid: thread.tid,
        title: thread.title,
        author: thread.author?.puname,
        authorPuid: thread.author?.puid,
        authorLevel: thread.author?.level,
        createdAt: thread.createdAt,
        createdAtFormat: thread.createdAtFormat,
        forumFid: thread.topic?.fid,
        forumName: thread.topic?.name,
        visits: thread.read,
        lights: thread.lights,
        recommend: thread.recommend,
        mainText: htmlToText(thread.content || ''),
        replyCount: detail.replies?.count ?? replies.length,
        replyList,
        myReplyCount: myReplies.length,
        myReplies: myReplies.map(r => r.content)
    };
}

const threadMeta = JSON.parse(readBOM(`${API_DIR}/all_threads.json`));
const outThreads = [];
for (const meta of threadMeta.threads) {
    const fp = `${THREADS_DIR}/${meta.tid}.html`;
    if (!fs.existsSync(fp)) continue;
    const html = readBOM(fp);
    const parsed = parseThread(html);
    if (parsed) {
        parsed.create_time = meta.create_time;
        parsed.fid = meta.fid;
        outThreads.push(parsed);
    }
}

// 统计
console.log(`Parsed ${outThreads.length}`);
const totalMyReplies = outThreads.reduce((s, t) => s + (t.myReplyCount||0), 0);
console.log(`User replies in their own threads: ${totalMyReplies}`);
const withText = outThreads.filter(t => t.mainText);
console.log(`Threads with main text: ${withText.length}/${outThreads.length}`);

// 时间范围
const dates = outThreads.map(t => new Date(t.create_time*1000));
console.log(`Date range: ${new Date(Math.min(...dates)).toISOString().slice(0,10)} - ${new Date(Math.max(...dates)).toISOString().slice(0,10)}`);

fs.writeFileSync(OUT_FILE, JSON.stringify({ count: outThreads.length, threads: outThreads }, null, 2));
console.log(`Saved ${OUT_FILE}`);

// parse_threads.js - 解析所有主帖的正文与回帖
const fs = require('fs');
const path = require('path');

const CRAWL = 'C:/Users/36997/crawl';
const THREADS_DIR = `${CRAWL}/threads`;
const API_DIR = `${CRAWL}/api`;
const OUT_FILE = `${CRAWL}/parsed_threads.json`;

function readBOM(file) {
    return fs.readFileSync(file, 'utf8').replace(/^﻿/, '');
}

function extractTitle(html) {
    const m = html.match(/<title[^>]*>([^<]+)<\/title>/);
    if (!m) return null;
    // 标题末尾带"-股票区-虎扑社区"之类的后缀
    let t = m[1].trim();
    return t;
}

function extractByClass(html, className) {
    const re = new RegExp(`<div class="[^"]*${className}[^"]*"[^>]*>([\\s\\S]*?)<\\/div>`, 'g');
    const matches = [];
    let m;
    while ((m = re.exec(html))) matches.push(m[1]);
    return matches;
}

function htmlToText(html) {
    return html
        .replace(/<br\s*\/?>/g, '\n')
        .replace(/<\/p>/g, '\n')
        .replace(/<img[^>]*src="([^"]+)"[^>]*\/?>/g, '[$1]')
        .replace(/<video[^>]*src="([^"]+)"[^>]*>[^<]*<\/video>/g, '[VIDEO:$1]')
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

// 抓主帖正文 + 主帖时间 + 回帖楼层
function parseThread(html) {
    const out = {
        title: extractTitle(html),
        mainPost: null,
        replies: [],
        stats: { hasMainPost: false, replyCount: 0 }
    };

    // 主帖正文容器：index_post-content 开头的元素 或包含大量"index_bbs-post-web-post-main"的 div
    // 简化：找第一个 post-wrapper 块
    const postRegex = /<div[^>]*class="[^"]*post-wrapper_bbs-post-wrapper[^"]*"[^>]*>([\s\S]*?)<\/div>\s*<\/div>\s*<\/div>/g;
    let blocks = [];
    let m;
    while ((m = postRegex.exec(html))) blocks.push(m[1]);
    if (blocks.length === 0) {
        // 退化：用 "index_mainPost__" 或 "hupu-post" 等
        const alt = /<div[^>]*class="[^"]*index_post-content[^"]*"[^>]*>([\s\S]*?)<\/div>\s*<div[^>]*post__/g;
        while ((m = alt.exec(html))) blocks.push(m[1]);
    }

    // 主帖时间 - 找第一个能匹配主帖时间的 div
    const timeMatch = html.match(/<span[^>]*class="[^"]*post-time[^"]*"[^>]*>([^<]+)<\/span>/);
    const mainTime = timeMatch ? timeMatch[1].trim() : null;

    if (blocks.length > 0) {
        const mainText = htmlToText(blocks[0]);
        if (mainText.length > 10) {
            out.mainPost = { content: mainText, time: mainTime };
            out.stats.hasMainPost = true;
        }
    }

    // 回帖列表：所有楼中楼回复（不含楼中楼嵌套）
    // 简易找所有 "index_bbs-post-web-post-subtitle" 后面的内容
    const replyRegex = /<div[^>]*class="[^"]*index_post-content[^"]*"[^>]*>([\s\S]*?)<\/div>\s*<\/li>/g;
    blocks = [];
    while ((m = replyRegex.exec(html))) blocks.push(m[1]);

    for (const block of blocks) {
        const text = htmlToText(block);
        if (text.length > 3) {
            out.replies.push(text);
        }
    }
    out.stats.replyCount = out.replies.length;

    return out;
}

// 主函数
const threadMeta = JSON.parse(readBOM(`${API_DIR}/all_threads.json`));
const outThreads = [];
let noMainCount = 0;
for (const meta of threadMeta.threads) {
    const fp = `${THREADS_DIR}/${meta.tid}.html`;
    if (!fs.existsSync(fp)) continue;
    const html = readBOM(fp);
    const parsed = parseThread(html);

    // 找该用户在主帖的回帖（在 HTML 中搜用户名）
    const userMentionsInHtml = (html.match(/海边的宁静/g) || []).length;

    outThreads.push({
        ...meta,
        ...parsed,
        userMentionsInHtml
    });
    if (!parsed.mainPost) noMainCount++;
}

console.log(`Parsed ${outThreads.length} threads.`);
console.log(`Threads without main post text: ${noMainCount}`);

// 显示无主帖的几个样例
console.log('\n=== Threads missing main post text ===');
for (const t of outThreads.filter(t => !t.mainPost).slice(0, 10)) {
    const d = new Date(t.create_time*1000).toISOString().slice(0,10);
    console.log(`[${t.tid}] ${d} fid=${t.fid} ${t.title}`);
}

// 按主帖字符长度排序 - 看一个中等长度的
console.log('\n=== median main post sample ===');
const withMain = outThreads.filter(t => t.mainPost && t.mainPost.content).sort((a,b) => a.mainPost.content.length - b.mainPost.content.length);
const median = withMain[Math.floor(withMain.length / 2)];
if (median) {
    console.log(`[${median.tid}] ${median.title}`);
    console.log('content length:', median.mainPost.content.length);
    console.log('content preview:');
    console.log(median.mainPost.content.slice(0, 600));
    console.log('replies in html:', median.replies.length);
}

fs.writeFileSync(OUT_FILE, JSON.stringify({ count: outThreads.length, threads: outThreads }, null, 2));
console.log(`\nSaved ${OUT_FILE}`);

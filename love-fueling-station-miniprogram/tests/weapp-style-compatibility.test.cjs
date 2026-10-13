const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

function collectScssFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) return collectScssFiles(target);
    return entry.isFile() && entry.name.endsWith('.scss') ? [target] : [];
  });
}

test('微信小程序样式不能包含 WXSS 不支持的 :has() 选择器', () => {
  const sourceRoot = path.join(__dirname, '..', 'src');
  const offenders = collectScssFiles(sourceRoot)
    .filter((file) => /:has\s*\(/.test(fs.readFileSync(file, 'utf8')))
    .map((file) => path.relative(path.join(__dirname, '..'), file));

  assert.deepEqual(offenders, [], `发现不兼容的 :has()：${offenders.join(', ')}`);
});

#!/usr/bin/env node
/**
 * migrate-data.mjs — 把一个数据目录原地改到新名字。
 *
 * 用途：插件改名之后，旧目录里的历史帧、索引、聊天记录还想接着用。
 * 不写死任何旧名字 —— 从哪搬到哪全部由参数决定：
 *
 *   node scripts/migrate-data.mjs <旧目录> [新目录]
 *   node scripts/migrate-data.mjs --from <旧目录> --to <新目录>
 *
 * 不给路径时，默认把 ~/.dsh 下最近改过的那个插件数据目录当作源，
 * 目标固定为 ~/.dsh/bionic。判断不了的会直接报错，不会盲搬。
 *
 * **必须在 DSH 停止时跑**：插件进程占着 chat.jsonl、语音日志和帧文件，
 * 目录改名会被系统拒绝。同盘改名是瞬时的，几个 GB 也不会复制一遍。
 * 目标目录已存在但是空的会被先删掉；非空则拒绝覆盖，等人确认。
 */

import { existsSync, readdirSync, renameSync, rmdirSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';

const dshHome = process.env.DSH_HOME || join(homedir(), '.dsh');

function argValue(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : null;
}

const positional = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const fromRaw = argValue('--from') ?? positional[0] ?? null;
const toRaw = argValue('--to') ?? positional[1] ?? null;

/** 没给源目录时，选 ~/.dsh 下最近修改的子目录（排除 bionic 自己）。 */
function guessFrom() {
  if (!existsSync(dshHome)) return null;
  const candidates = readdirSync(dshHome)
    .filter((name) => name !== 'bionic' && !name.startsWith('.'))
    .map((name) => join(dshHome, name))
    .filter((p) => {
      try { return statSync(p).isDirectory(); } catch { return false; }
    })
    .map((p) => ({ p, mtime: statSync(p).mtimeMs }))
    .sort((a, b) => b.mtime - a.mtime);
  return candidates[0]?.p ?? null;
}

const from = fromRaw ? resolve(fromRaw) : guessFrom();
const to = resolve(toRaw ?? join(dshHome, 'bionic'));

if (!from) {
  console.error('找不到要迁移的源目录。');
  console.error('用法：node scripts/migrate-data.mjs <旧目录> [新目录]');
  process.exit(1);
}

if (resolve(from) === to) {
  console.error(`源和目标是同一个目录：${from}`);
  process.exit(1);
}

if (!existsSync(from)) {
  console.log(`源目录不存在：${from}`);
  console.log('如果已经迁移过，直接启动 DSH 即可。');
  process.exit(0);
}

if (existsSync(to)) {
  const entries = readdirSync(to);
  if (entries.length) {
    console.log(`目标目录非空：${to}`);
    console.log(`里面有 ${entries.length} 项，不覆盖。请先人工确认。`);
    process.exit(1);
  }
  rmdirSync(to);
  console.log('已删掉改名后新建的空目录');
}

try {
  renameSync(from, to);
} catch (error) {
  console.error(`迁移失败：${error.message}`);
  console.error('先完全退出 DSH（所有进程），再重跑。');
  process.exit(1);
}

console.log(`已迁移：${from}`);
console.log(`     →  ${to}`);
console.log('启动 DSH 即可，历史帧、索引、聊天记录都还在。');

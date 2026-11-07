#!/usr/bin/env node
/**
 * update.mjs — 从 GitHub 主分支拉最新版，覆盖当前安装。
 *
 * 不写死版本号：永远取 `refs/heads/main` 的 tar.gz，
 * 所以每次跑这个脚本拿到的都是作者当前发布的最新代码。
 *
 *   node scripts/update.mjs              # 更新默认 profile 里的安装
 *   node scripts/update.mjs --dir <路径>  # 更新指定目录
 *   node scripts/update.mjs --dry-run     # 只看会更新到哪一版，不动文件
 *
 * 只覆盖程序文件（dist / examples / scripts / docs / 清单和文档），
 * **不碰** ~/.dsh/bionic 下的数据，也不碰 profile 的 node_modules 其它内容。
 */

import { createWriteStream, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync,
  rmSync, statSync, cpSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { pipeline } from 'node:stream/promises';

const REPO = 'greenteagmail-droid/DSH';
const BRANCH = 'main';
const TARBALL = `https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz`;

const args = process.argv.slice(2);
const argValue = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : null;
};
const dryRun = args.includes('--dry-run');

function defaultTarget() {
  const home = process.env.DSH_HOME || join(homedir(), '.dsh');
  const profiles = join(home, 'profiles');
  // 优先 desktop；没有就取第一个装了本插件的 profile
  const candidates = [];
  try {
    for (const name of readdirSync(profiles)) {
      const p = join(profiles, name, 'node_modules', 'dsh-bionic-intelligence');
      if (existsSync(p)) candidates.push(p);
    }
  } catch { /* 没有 profiles 目录 */ }
  const desktop = candidates.find((p) => p.includes(`${join('profiles', 'desktop')}`));
  return desktop ?? candidates[0] ?? null;
}

const target = argValue('--dir') ? resolve(argValue('--dir')) : defaultTarget();
if (!target) {
  console.error('找不到已安装的插件目录。用 --dir 指定，例如：');
  console.error('  node scripts/update.mjs --dir ~/.dsh/profiles/desktop/node_modules/dsh-bionic-intelligence');
  process.exit(1);
}

const work = mkdtempSync(join(tmpdir(), 'bionic-update-'));
const zip = join(work, 'main.tar.gz');

/** 系统代理：curl 不读 Windows 的「Internet 选项」，只能自己取出来传给它。 */
function systemProxy() {
  for (const key of ['HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy']) {
    const v = process.env[key];
    if (v) return v;
  }
  if (process.platform !== 'win32') return null;
  try {
    const out = execFileSync('powershell.exe', ['-NoProfile', '-Command',
      "(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings').ProxyServer"],
    { encoding: 'utf8', timeout: 15_000, windowsHide: true }).trim();
    if (out && /:\d+/.test(out)) return `http://${out}`;
  } catch { /* 没有代理 */ }
  return null;
}

async function download() {
  const proxy = systemProxy();
  if (proxy) console.log(`走代理：${proxy}`);
  // 优先 curl.exe：Node 自带的 fetch 不读代理，直连 GitHub 在国内基本不通。
  const curlArgs = ['-L', '--retry', '2', '--connect-timeout', '20', '-o', zip, TARBALL];
  if (proxy) curlArgs.unshift('--proxy', proxy);
  try {
    execFileSync('curl.exe', curlArgs, { stdio: 'ignore', timeout: 240_000 });
    if (existsSync(zip) && statSync(zip).size > 1024) return;
  } catch { /* 没有 curl 或失败，退回 fetch */ }

  const res = await fetch(TARBALL, { redirect: 'follow' });
  if (!res.ok) throw new Error(`下载失败 HTTP ${res.status}`);
  await pipeline(res.body, createWriteStream(zip));
}

function extract() {
  const out = join(work, 'x');
  mkdirSync(out, { recursive: true });
  // Windows 10+ 自带 tar.exe；没有就退回 PowerShell 的 tar
  try {
    execFileSync('tar.exe', ['-xzf', zip, '-C', out], { stdio: 'ignore', timeout: 120_000 });
  } catch {
    execFileSync('powershell.exe', ['-NoProfile', '-Command',
      `tar -xzf '${zip}' -C '${out}'`], { stdio: 'ignore', timeout: 120_000 });
  }
  const top = readdirSync(out).map((n) => join(out, n)).find((p) => statSync(p).isDirectory());
  if (!top) throw new Error('解压后找不到顶层目录');
  return top;
}

function currentVersion() {
  try {
    return JSON.parse(readFileSync(join(target, 'package.json'), 'utf8')).version ?? '?';
  } catch { return '?'; }
}

function copyOver(src) {
  // 只覆盖程序文件，别的都留着
  const items = ['dist', 'examples', 'scripts', 'docs', 'cordis.patch.yml',
    'dsh.plugin.json', 'package.json', 'README.md', 'CHANGELOG.md', 'INSTALL.md',
    'REPAIR.md', 'VERIFY.md', 'LICENSE'];
  let copied = 0;
  for (const name of items) {
    const from = join(src, name);
    if (!existsSync(from)) continue;
    const to = join(target, name);
    rmSync(to, { recursive: true, force: true });
    cpSync(from, to, { recursive: true });
    copied += 1;
  }
  return copied;
}

try {
  console.log(`目标安装：${target}`);
  console.log(`当前版本：${currentVersion()}`);
  console.log(`拉取分支：${REPO}@${BRANCH}`);

  await download();
  const src = extract();
  const nextVersion = (() => {
    try { return JSON.parse(readFileSync(join(src, 'package.json'), 'utf8')).version ?? '?'; }
    catch { return '?'; }
  })();

  if (dryRun) {
    console.log(`\n--dry-run：会更新到 ${nextVersion}，未改动任何文件。`);
    process.exit(0);
  }

  const copied = copyOver(src);
  console.log(`\n已更新到 ${nextVersion}（覆盖 ${copied} 项）`);
  console.log('**重启 DSH 生效**（窗口进程也要重开）。');
  console.log('数据目录 ~/.dsh/bionic 没有被改动。');
} catch (e) {
  console.error(`\n更新失败：${e?.message ?? e}`);
  console.error('网络不通时可以先开代理，或者手动下载：');
  console.error(`  ${TARBALL}`);
  process.exit(1);
} finally {
  try { rmSync(work, { recursive: true, force: true }); } catch { /* 清不掉就算了 */ }
}

#!/usr/bin/env node
/**
 * install-dev.mjs — 把这个包同步进 DSH 的 desktop profile。
 *
 *   node scripts/install-dev.mjs            安装 / 同步
 *   node scripts/install-dev.mjs --check    只看状态，不动文件
 *   node scripts/install-dev.mjs --remove   卸载
 *
 * 必须手动做，因为 desktop profile 由 Electron 应用独占管理，
 * `dsh plugin --profile desktop ...` 会被直接拒绝。
 *
 * 默认是复制，不是软链：Node 解析裸包名（@deepseek-ai/dsh-tools）用的是真实路径，
 * 软链会让它从源码目录往上找，找不到宿主那一份。复制进 profile 的 node_modules，
 * 解析链才是 profiles/desktop/node_modules → profiles/node_modules。
 *
 * 本机目前用另一种装法：源码目录里放一份 node_modules/@deepseek-ai/schemastery
 * 指回 profile，profile 依赖写 link:，盘上只有一份代码。检测到这种装法就不再复制，
 * 否则又变成两处，改哪边都对不齐。
 */

import { cp, readFile, writeFile, rm } from 'node:fs/promises';
import { existsSync, lstatSync, realpathSync, rmdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { homedir } from 'node:os';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const DSH_HOME = process.env.DSH_HOME || join(homedir(), '.dsh');
const PROFILE_NAME = process.env.DSH_PROFILE || 'desktop';
const PROFILE_DIR = join(DSH_HOME, 'profiles', PROFILE_NAME);
const MODULES = join(PROFILE_DIR, 'node_modules');
const PACKAGE = 'dsh-bionic-intelligence';
const PROFILE_JSON = join(PROFILE_DIR, 'package.json');

/**
 * 复制时跳过这些目录：
 *   .tmp / debug   调试产物，被占用的文件会让复制中途失败
 *   test / scripts 测试和工具脚本，不进插件
 *   __pycache__    Python 编译缓存，拷过去只会让旧字节码跟着走
 */
const SKIP = new Set(['node_modules', '.git', 'test', '.tmp', 'scripts', 'debug', '__pycache__']);

const mode = process.argv.includes('--remove') ? 'remove'
  : process.argv.includes('--check') ? 'check'
    : 'install';

const readProfile = async () => JSON.parse(await readFile(PROFILE_JSON, 'utf8'));

/** profile 里那个包是不是指回本目录的链接。是的话说明已经是单一源码装法。 */
function linkedBackHere() {
  const target = join(MODULES, PACKAGE);
  try {
    if (lstatSync(target).isSymbolicLink()) return true;
    return realpathSync(target).toLowerCase() === realpathSync(ROOT).toLowerCase();
  } catch {
    return false;
  }
}

async function describe() {
  const pkg = await readProfile();
  const bundles = pkg.dsh?.profile?.bundles ?? [];
  const installed = existsSync(join(MODULES, PACKAGE));
  const registered = bundles.includes(PACKAGE);
  const linked = linkedBackHere();

  console.log(`profile   : ${PROFILE_DIR}`);
  console.log(`${PACKAGE}: ${installed ? '已安装' : '未安装'}${linked ? '（链接，单一源码）' : ''}  `
    + `bundles ${registered ? '已注册' : '未注册'}`);
  console.log(`bundles 共 ${bundles.length} 项：${bundles.join(', ')}`);

  return { installed, registered, linked };
}

async function updateProfile({ add }) {
  const pkg = await readProfile();
  const bundles = pkg.dsh?.profile?.bundles ?? [];
  const alreadyThere = Object.hasOwn(pkg.dependencies ?? {}, PACKAGE);

  if (add) {
    if (!alreadyThere) {
      const stamp = new Date().toISOString().replace(/[:.]/g, '-');
      const backup = join(PROFILE_DIR, `package.json.bak-${stamp}-bionic`);
      await writeFile(backup, await readFile(PROFILE_JSON), 'utf8');
      console.log(`已备份 package.json → ${backup}`);
    }
    pkg.dependencies = {
      ...(pkg.dependencies ?? {}),
      [PACKAGE]: `file:${ROOT.replace(/\\/g, '/')}`,
    };
    pkg.dsh = pkg.dsh ?? {};
    pkg.dsh.profile = pkg.dsh.profile ?? {};
    if (!bundles.includes(PACKAGE)) pkg.dsh.profile.bundles = [...bundles, PACKAGE];
  } else {
    if (pkg.dependencies) delete pkg.dependencies[PACKAGE];
    if (pkg.dsh?.profile?.bundles) {
      pkg.dsh.profile.bundles = pkg.dsh.profile.bundles.filter((name) => name !== PACKAGE);
    }
  }
  await writeFile(PROFILE_JSON, `${JSON.stringify(pkg, null, 2)}\n`, 'utf8');
}

async function main() {
  if (!existsSync(PROFILE_DIR)) {
    console.error(`profile 不存在：${PROFILE_DIR}`);
    process.exit(2);
  }

  if (mode === 'check') {
    await describe();
    return;
  }

  if (mode === 'remove') {
    // 链接装法只摘链接。递归删除会顺着链接摸到源码目录，绝对不行。
    if (linkedBackHere()) rmdirSync(join(MODULES, PACKAGE));
    else await rm(join(MODULES, PACKAGE), { recursive: true, force: true });

    await updateProfile({ add: false });
    console.log('已卸载 Bionic Intelligence。重启 DSH 生效。');
    await describe();
    return;
  }

  if (linkedBackHere()) {
    console.log('profile 里已经是链接（单一源码装法），不复制，避免出现两份代码。');
    await describe();
    return;
  }

  // 安装闸门：运行支撑不全就拒绝安装。全量硬校验，不做降级。
  const { runDoctor, renderDoctor } = await import('../src/doctor.js');
  const report = runDoctor();
  if (!report.ok) {
    process.stderr.write(renderDoctor(report));
    console.error('\n缺少运行支撑，已取消安装。补齐后重跑：node scripts/install-dev.mjs');
    process.exit(3);
  }

  await rm(join(MODULES, PACKAGE), { recursive: true, force: true });
  await cp(ROOT, join(MODULES, PACKAGE), {
    recursive: true,
    filter: (source) => !SKIP.has(source.split(/[\\/]/).pop()),
  });
  await updateProfile({ add: true });

  console.log('已安装。重启 DSH 生效，然后让模型调 `bionic({ action: "record" })`。');
  await describe();
}

await main();

import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const script = fileURLToPath(new URL('./package-dist.mjs', import.meta.url));

function run(mode, built, packaged) {
  return spawnSync(
    process.execPath,
    [script, mode, '--built', built, '--packaged', packaged],
    { encoding: 'utf8' },
  );
}

async function fixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), 'groundball-web-dist-'));
  const built = path.join(root, 'built');
  const packaged = path.join(root, 'packaged');
  await mkdir(path.join(built, 'assets'), { recursive: true });
  await mkdir(path.join(packaged, 'stale'), { recursive: true });
  await writeFile(path.join(built, 'index.html'), Buffer.from([0x3c, 0x68, 0x31, 0x3e]));
  await writeFile(path.join(built, 'assets', 'app.js'), Buffer.from([0x00, 0x7f, 0x80, 0xff]));
  await writeFile(path.join(packaged, 'stale', 'old.js'), 'obsolete');
  return { root, built, packaged };
}

test('sync replaces the packaged fallback with the exact recursive build output', async () => {
  const { root, built, packaged } = await fixture();
  try {
    const result = run('sync', built, packaged);
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(
      await readFile(path.join(packaged, 'assets', 'app.js')),
      await readFile(path.join(built, 'assets', 'app.js')),
    );
    await assert.rejects(readFile(path.join(packaged, 'stale', 'old.js')));
    assert.equal(run('check', built, packaged).status, 0);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('check rejects extra, missing, and byte-different fallback files', async () => {
  const { root, built, packaged } = await fixture();
  try {
    assert.equal(run('sync', built, packaged).status, 0);

    await writeFile(path.join(packaged, 'extra.txt'), 'extra');
    let result = run('check', built, packaged);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /unexpected packaged files: extra\.txt/);

    assert.equal(run('sync', built, packaged).status, 0);
    await rm(path.join(packaged, 'index.html'));
    result = run('check', built, packaged);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /missing packaged files: index\.html/);

    assert.equal(run('sync', built, packaged).status, 0);
    await writeFile(path.join(packaged, 'assets', 'app.js'), Buffer.from([0x00, 0x7f, 0x80, 0x00]));
    result = run('check', built, packaged);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /byte differences: assets\/app\.js/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

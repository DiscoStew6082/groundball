import { mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const webRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const defaultBuilt = path.join(webRoot, 'dist');
const defaultPackaged = path.resolve(webRoot, '..', 'src', 'baseball_rag', 'web_dist');

async function relativeFiles(root, current = root) {
  const entries = await readdir(current, { withFileTypes: true });
  const files = [];
  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    const absolute = path.join(current, entry.name);
    if (entry.isDirectory()) {
      files.push(...await relativeFiles(root, absolute));
    } else if (entry.isFile()) {
      files.push(path.relative(root, absolute).split(path.sep).join('/'));
    } else {
      throw new Error(`unsupported non-file entry: ${path.relative(root, absolute)}`);
    }
  }
  return files;
}

export async function syncPackage(built, packaged) {
  const files = await relativeFiles(built);
  await rm(packaged, { recursive: true, force: true });
  await mkdir(packaged, { recursive: true });
  for (const relative of files) {
    const destination = path.join(packaged, ...relative.split('/'));
    await mkdir(path.dirname(destination), { recursive: true });
    await writeFile(destination, await readFile(path.join(built, ...relative.split('/'))));
  }
  return files;
}

export async function checkPackage(built, packaged) {
  const builtFiles = await relativeFiles(built);
  const packagedFiles = await relativeFiles(packaged);
  const builtSet = new Set(builtFiles);
  const packagedSet = new Set(packagedFiles);
  const missing = builtFiles.filter((relative) => !packagedSet.has(relative));
  const unexpected = packagedFiles.filter((relative) => !builtSet.has(relative));
  const different = [];

  for (const relative of builtFiles.filter((candidate) => packagedSet.has(candidate))) {
    const [builtBytes, packagedBytes] = await Promise.all([
      readFile(path.join(built, ...relative.split('/'))),
      readFile(path.join(packaged, ...relative.split('/'))),
    ]);
    if (!builtBytes.equals(packagedBytes)) {
      different.push(relative);
    }
  }

  const drift = [];
  if (missing.length) drift.push(`missing packaged files: ${missing.join(', ')}`);
  if (unexpected.length) drift.push(`unexpected packaged files: ${unexpected.join(', ')}`);
  if (different.length) drift.push(`byte differences: ${different.join(', ')}`);
  if (drift.length) {
    throw new Error(drift.join('; '));
  }
  return builtFiles;
}

function argumentsFrom(argv) {
  const [mode, ...options] = argv;
  if (!['sync', 'check'].includes(mode)) {
    throw new Error('usage: package-dist.mjs <sync|check> [--built DIR] [--packaged DIR]');
  }
  const paths = { built: defaultBuilt, packaged: defaultPackaged };
  for (let index = 0; index < options.length; index += 2) {
    const flag = options[index];
    const value = options[index + 1];
    if (!value || !['--built', '--packaged'].includes(flag)) {
      throw new Error(`invalid option: ${flag ?? ''}`);
    }
    paths[flag === '--built' ? 'built' : 'packaged'] = path.resolve(value);
  }
  return { mode, ...paths };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const { mode, built, packaged } = argumentsFrom(process.argv.slice(2));
    const files = mode === 'sync'
      ? await syncPackage(built, packaged)
      : await checkPackage(built, packaged);
    console.log(`${mode} complete: ${files.length} files`);
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}

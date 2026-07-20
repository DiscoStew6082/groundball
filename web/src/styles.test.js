import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

const stylesheet = readFileSync(resolve(process.cwd(), 'src/styles.css'), 'utf8');

function mediaBlock(query) {
  const start = stylesheet.indexOf(`@media ${query}`);
  if (start < 0) return '';
  const open = stylesheet.indexOf('{', start);
  let depth = 1;
  for (let index = open + 1; index < stylesheet.length; index += 1) {
    if (stylesheet[index] === '{') depth += 1;
    if (stylesheet[index] === '}') depth -= 1;
    if (depth === 0) return stylesheet.slice(open + 1, index);
  }
  return '';
}

function declarations(block, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return block.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`))?.[1] ?? '';
}

const mobile = mediaBlock('(max-width: 600px)');

describe('390px result layout contract', () => {
  it('fits the four required result columns and swaps only their visible headings', () => {
    expect(declarations(mobile, '.four-column-result')).toContain('table-layout: fixed');
    expect(declarations(mobile, '.four-column-result th, .four-column-result td')).toMatch(/min-width:\s*0/);
    expect(declarations(mobile, '.four-column-result th, .four-column-result td')).toMatch(/white-space:\s*normal/);
    expect(declarations(mobile, '.desktop-heading')).toMatch(/display:\s*none/);
    expect(declarations(mobile, '.mobile-heading')).toMatch(/display:\s*inline/);
  });

  it('keeps the composer in document flow below results on mobile', () => {
    expect(declarations(mobile, '.composer-dock')).toMatch(/position:\s*static/);
    expect(declarations(mobile, '.composer-dock')).toMatch(/transform:\s*none/);
  });

  it('keeps pagination on one compact operable row', () => {
    expect(declarations(mobile, '.pagination-controls')).toMatch(/flex-direction:\s*row/);
    expect(declarations(mobile, '.pagination-controls select')).toMatch(/width:\s*auto/);
    expect(declarations(mobile, '.pagination-controls button')).toMatch(/min-width:\s*44px/);
  });
});

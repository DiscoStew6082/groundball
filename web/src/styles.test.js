import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

const styles = readFileSync(resolve(process.cwd(), 'src/styles.css'), 'utf8');

describe('Ground Ball responsive stylesheet', () => {
  it('preserves the application frame and usable controls at phone widths', () => {
    const phoneStart = styles.search(/@media\s*\(max-width:\s*480px\)/);
    const phoneStyles = phoneStart === -1 ? '' : styles.slice(phoneStart);

    expect(phoneStart).toBeGreaterThanOrEqual(0);
    expect(phoneStyles).toMatch(/\.app-window\s*{[^}]*border:\s*1px solid/);
    expect(phoneStyles).toContain(
      'min-height: calc(100dvh - max(8px, env(safe-area-inset-top)) - max(8px, env(safe-area-inset-bottom)))',
    );
    expect(phoneStyles).toMatch(/\.ask-button\s*{[^}]*width:\s*100%[^}]*min-height:\s*48px/);
    expect(phoneStyles).toMatch(/\.conversation-turn p\s*{[^}]*grid-template-columns:\s*1fr/);
    expect(phoneStyles).toMatch(/\.nav-item,[^{]*\.download-row a[^{]*{[^}]*min-height:\s*44px/);
    expect(phoneStyles).toMatch(/\.answer-copy,[^{]*\.history-list span[^{]*{[^}]*overflow-wrap:\s*anywhere/);
  });
});

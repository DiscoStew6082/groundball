import { mount, tick } from 'svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App.svelte';

const capabilities = {
  name: 'Ground Ball',
  mode: 'local',
  query: {
    endpoint: '/api/query-runs',
    catalog_endpoint: '/api/query-catalog',
    natural_language: true,
    structured_recipe: true,
  },
  history: 'browser_local',
};

const catalog = {
  catalog_revision: 'published-query-catalog-v3',
  sources: [{ identity: 'Batting', kind: 'packaged_lahman_table', reference_version: null }],
  fields: [
    {
      identity: 'Batting.GIDP',
      source: 'Batting',
      column: 'GIDP',
      data_type: 'integer',
      operations: ['select', 'equals', 'sort', 'export'],
    },
  ],
  values: [
    {
      identity: 'batting.OPS',
      friendly_name: 'On-base plus slugging',
      formula: 'OBP + SLG',
      allowed_grains: ['player-season'],
    },
  ],
  relationships: [],
};

const recipe = {
  catalog_revision: null,
  source: 'Batting',
  grain: 'player-season',
  selections: ['player.name', 'season', 'batting.HR', 'batting.SB'],
  groupings: [],
  ordering: [],
  output: { kind: 'interactive_page', size: 25, offset: 0 },
  predicate: null,
  ranking: null,
};

const rowsRun = {
  kind: 'rows',
  recipe,
  plan: { ...recipe, version: 'query-plan-v1', relationships: [] },
  rows: [
    { 'player.name': 'Jose Canseco', season: 1988, 'batting.HR': 42, 'batting.SB': 40 },
    { 'player.name': 'Shohei Ohtani', season: 2024, 'batting.HR': 54, 'batting.SB': 59 },
  ],
  evidence: {
    parameterized_sql: 'SELECT player, SUM(HR) FROM batting WHERE HR >= ?',
    bound_values: [40],
    sources: [{ identity: 'Batting', release: 'lahman-2025', row_fingerprint: 'abc' }],
    calculations: [{ identity: 'batting.OPS', formula: 'OBP + SLG', inputs: ['H', 'AB'] }],
    catalog_revision: 'published-query-catalog-v3',
    data_release: 'lahman-2025',
    row_count: 2,
    matched_row_count: 2,
    result_fingerprint: 'result-123',
  },
  verification: {
    status: 'unavailable',
    reason: 'No passing Coverage Report exists for this catalog and data release.',
    coverage_report: null,
  },
  returned_row_count: 2,
  total_matched_count: 2,
  pagination: { size: 25, offset: 0, has_more: false },
};

function response(payload, ok = true, status = ok ? 200 : 500) {
  return Promise.resolve({ ok, status, json: () => Promise.resolve(payload) });
}

function inputText(label, value) {
  const input = document.querySelector(`[aria-label="${label}"]`);
  input.value = value;
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

async function mountApp(runHandler = () => response(rowsRun)) {
  const fetchMock = vi.fn((url, options) => {
    if (url === '/api/capabilities') return response(capabilities);
    if (url === '/api/query-catalog') return response(catalog);
    if (url === '/api/query-runs') return runHandler(JSON.parse(options.body));
    throw new Error(`Unexpected URL ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  mount(App, { target: document.body });
  await vi.waitFor(() => expect(document.body.textContent).toContain('Ready'));
  return fetchMock;
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn(() => 'blob:ground-ball-export'),
    revokeObjectURL: vi.fn(),
  });
});

describe('Ground Ball answer-first application', () => {
  it('runs the editable 40-40 example and exposes one evidence-complete Details surface', async () => {
    const fetchMock = await mountApp();

    expect(document.querySelector('[aria-label="Ask Ground Ball"]').value).toBe('40-40');
    expect(document.querySelector('[aria-label="Open application navigation"]')).not.toBeNull();
    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));

    await vi.waitFor(() => expect(document.body.textContent).toContain('Jose Canseco'));
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/query-runs',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ question: '40-40' }) }),
    );
    expect(document.body.textContent).toContain('2 matching rows');

    document.querySelector('[aria-label="Open query details"]').click();
    await tick();
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    expect(document.body.textContent).toContain('Query Plan');
    expect(document.body.textContent).toContain('OBP + SLG');
    expect(document.body.textContent).toContain('Verification unavailable');
    expect(document.body.textContent).toContain('SELECT player');
    expect(document.body.textContent).toContain('Browse fields');
    expect(document.activeElement.getAttribute('aria-label')).toBe('Close details');

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await vi.waitFor(() => expect(document.querySelector('[role="dialog"]')).toBeNull());
    await vi.waitFor(() =>
      expect(document.activeElement.getAttribute('aria-label')).toBe('Open query details'),
    );
  });

  it('keeps the last completed table visible while the next attempt is pending', async () => {
    let finishSecond;
    const secondResponse = new Promise((resolve) => {
      finishSecond = resolve;
    });
    let calls = 0;
    await mountApp(() => {
      calls += 1;
      return calls === 1 ? response(rowsRun) : secondResponse;
    });

    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));
    await vi.waitFor(() => expect(document.body.textContent).toContain('Jose Canseco'));

    inputText('Ask Ground Ball', 'a second question');
    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));
    await vi.waitFor(() => expect(document.body.textContent).toContain('Planning and checking'));
    expect(document.body.textContent).toContain('Jose Canseco');

    finishSecond(response(rowsRun));
    await vi.waitFor(() => expect(calls).toBe(2));
  });

  it.each([
    ['busy', { error: 'busy', reason: 'visitor_run_active', detail: 'Another Query Run is active.', retry_at: '2026-07-19T12:00:15+00:00' }, 429, 'Retry at 2026-07-19T12:00:15+00:00.'],
    ['rate limited', { error: 'rate_limited', reason: 'three_starts_per_minute', detail: 'Three starts per minute reached.', retry_at: '2026-07-19T12:01:00+00:00' }, 429, 'Retry at 2026-07-19T12:01:00+00:00.'],
    ['timed out', { error: 'timed_out', detail: 'The Query Run timed out. Narrow the question.' }, 503, 'Narrow the question.'],
    ['export too large', { error: 'export_too_large', detail: 'The complete export is too large.', guidance: 'Add filters to narrow the result, then export again.' }, 422, 'Add filters to narrow the result, then export again.'],
    ['allowance paused', { error: 'allowance_paused', detail: 'The public allowance is paused.', retry_at: '2026-08-01T00:00:00+00:00' }, 503, 'Retry at 2026-08-01T00:00:00+00:00.'],
    ['provider unavailable', { error: 'provider_unavailable', detail: 'The public provider is unavailable.' }, 503, 'The public provider is unavailable.'],
  ])('preserves a completed table across structured %s refusal', async (_label, refusal, status, actionableText) => {
    let calls = 0;
    const fetchMock = await mountApp(() => {
      calls += 1;
      return calls === 1 ? response(rowsRun) : response(refusal, false, status);
    });

    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));
    await vi.waitFor(() => expect(document.body.textContent).toContain('Jose Canseco'));
    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));

    await vi.waitFor(() => expect(document.body.textContent).toContain(actionableText));
    expect(document.body.textContent).toContain('Jose Canseco');
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it.each([
    ['unsupported query', { kind: 'rejected', reason: 'That comparison is not published.' }, 'That comparison is not published.'],
    ['unavailable query', { kind: 'unavailable', reason: 'Coverage proof is unavailable.' }, 'Coverage proof is unavailable.'],
    ['failed query', { kind: 'failed', reason: 'The deterministic query failed.' }, 'The deterministic query failed.'],
    ['clarification', { kind: 'needs_clarification', question: 'Which league?', choices: [] }, 'Which league?'],
  ])('preserves a completed table across a successful %s outcome', async (_label, outcome, text) => {
    let calls = 0;
    const fetchMock = await mountApp(() => {
      calls += 1;
      return response(calls === 1 ? rowsRun : outcome);
    });

    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));
    await vi.waitFor(() => expect(document.body.textContent).toContain('Jose Canseco'));
    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));

    await vi.waitFor(() => expect(document.body.textContent).toContain(text));
    expect(document.body.textContent).toContain('Jose Canseco');
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it('preserves a completed table when the latest response is malformed', async () => {
    let calls = 0;
    const fetchMock = await mountApp(() => {
      calls += 1;
      if (calls === 1) return response(rowsRun);
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.reject(new SyntaxError('invalid JSON')),
      });
    });

    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));
    await vi.waitFor(() => expect(document.body.textContent).toContain('Jose Canseco'));
    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));

    await vi.waitFor(() => expect(document.body.textContent).toContain('Malformed response'));
    expect(document.body.textContent).toContain('Jose Canseco');
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it('paginates the same completed recipe by changing only output size and offset', async () => {
    const firstPage = {
      ...rowsRun,
      total_matched_count: 52,
      pagination: { size: 25, offset: 0, has_more: true },
    };
    const requests = [];
    await mountApp((body) => {
      requests.push(body);
      if (requests.length === 1) return response(firstPage);
      return response({
        ...firstPage,
        recipe: body.recipe,
        plan: { ...firstPage.plan, output: body.recipe.output },
        pagination: {
          size: body.recipe.output.size,
          offset: body.recipe.output.offset,
          has_more: body.recipe.output.offset + body.recipe.output.size < 52,
        },
      });
    });

    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));
    await vi.waitFor(() => expect(document.body.textContent).toContain('returned 2 of 52 matched'));
    expect(document.querySelector('[aria-label="Previous page"]').disabled).toBe(true);
    expect(document.querySelector('[aria-label="Next page"]').disabled).toBe(false);

    document.querySelector('[aria-label="Next page"]').click();
    await vi.waitFor(() => expect(requests).toHaveLength(2));
    await vi.waitFor(() => expect(document.querySelector('[aria-label="Next page"]').disabled).toBe(false));
    expect(requests[1]).toEqual({
      recipe: { ...recipe, output: { kind: 'interactive_page', size: 25, offset: 25 } },
    });

    const pageSize = document.querySelector('[aria-label="Rows per page"]');
    pageSize.value = '50';
    pageSize.dispatchEvent(new Event('change', { bubbles: true }));
    await vi.waitFor(() => expect(requests).toHaveLength(3));
    expect(requests[2]).toEqual({
      recipe: { ...recipe, output: { kind: 'interactive_page', size: 50, offset: 0 } },
    });
  });

  it('records successful no-data as the latest completed run', async () => {
    const noData = {
      ...rowsRun,
      kind: 'no_data',
      rows: [],
      returned_row_count: 0,
      total_matched_count: 0,
      pagination: { size: 25, offset: 0, has_more: false },
    };
    let calls = 0;
    await mountApp(() => {
      calls += 1;
      return response(calls === 1 ? rowsRun : noData);
    });

    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));
    await vi.waitFor(() => expect(document.body.textContent).toContain('Jose Canseco'));
    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));

    await vi.waitFor(() => expect(document.body.textContent).toContain('returned 0 of 0 matched'));
    expect(document.body.textContent).toContain('No matching rows');
    expect(document.body.textContent).not.toContain('Jose Canseco');
    expect(JSON.parse(localStorage.getItem('ground-ball-query-history'))).toHaveLength(2);
  });

  it('renders truthful counts and controls for an exhausted nonzero page', async () => {
    const exhausted = {
      ...rowsRun,
      rows: [],
      returned_row_count: 0,
      total_matched_count: 52,
      pagination: { size: 25, offset: 75, has_more: false },
    };
    await mountApp(() => response(exhausted));

    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));

    await vi.waitFor(() => expect(document.body.textContent).toContain('returned 0 of 52 matched'));
    expect(document.querySelector('[aria-label="Previous page"]').disabled).toBe(false);
    expect(document.querySelector('[aria-label="Next page"]').disabled).toBe(true);
    expect(document.querySelector('[data-testid="results"]')).toBeNull();
  });

  it('downloads one complete export without replacing the completed query', async () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    let calls = 0;
    const fetchMock = await mountApp(() => {
      calls += 1;
      return response(calls === 1 ? rowsRun : {
        ...rowsRun,
        kind: 'exported',
        export: { format: 'csv', content: 'player.name,season\nJose Canseco,1988\n' },
      });
    });

    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));
    await vi.waitFor(() => expect(document.body.textContent).toContain('Jose Canseco'));
    document.querySelector('[aria-label="Open query details"]').click();
    await tick();
    [...document.querySelectorAll('.details-actions button')]
      .find((button) => button.textContent === 'Export CSV')
      .click();

    await vi.waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
    expect(document.body.textContent).toContain('Jose Canseco');
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it('keeps the completed query and downloads nothing when export is refused', async () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    let calls = 0;
    const fetchMock = await mountApp(() => {
      calls += 1;
      return calls === 1
        ? response(rowsRun)
        : response({
            error: 'export_too_large',
            detail: 'The complete export exceeds the public matched rows ceiling.',
            guidance: 'Add filters to narrow the result, then export again.',
          }, false, 422);
    });

    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));
    await vi.waitFor(() => expect(document.body.textContent).toContain('Jose Canseco'));
    document.querySelector('[aria-label="Open query details"]').click();
    await tick();
    [...document.querySelectorAll('.details-actions button')]
      .find((button) => button.textContent === 'Export JSON')
      .click();

    await vi.waitFor(() => expect(document.body.textContent).toContain('Add filters to narrow the result, then export again.'));
    expect(document.body.textContent).toContain('Jose Canseco');
    expect(clickSpy).not.toHaveBeenCalled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it('renders a focused clarification inline and applies its structured recipe choice', async () => {
    const pitchingRecipe = {
      ...recipe,
      source: 'Pitching',
      selections: ['player.id', 'season', 'pitching.SO'],
    };
    const clarification = {
      kind: 'needs_clarification',
      question: 'Should strikeouts mean batting or pitching strikeouts?',
      choices: [
        { label: 'Pitching', recipe: pitchingRecipe },
        { label: 'Batting', recipe },
      ],
      recipe: null,
      plan: null,
    };
    const pitchingRun = {
      ...rowsRun,
      recipe: pitchingRecipe,
      plan: { ...pitchingRecipe, version: 'query-plan-v1', relationships: [] },
      rows: [{ 'player.id': 'skubata01', season: 2024, 'pitching.SO': 228 }],
    };
    let calls = 0;
    const fetchMock = await mountApp((body) => {
      calls += 1;
      return response(calls === 1 ? clarification : pitchingRun);
    });

    inputText('Ask Ground Ball', 'who had the most strikeouts in 2024');
    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));
    await vi.waitFor(() =>
      expect(document.body.textContent.toLowerCase()).toContain('batting or pitching'),
    );

    [...document.querySelectorAll('.clarification-choice')]
      .find((button) => button.textContent.includes('Pitching'))
      .click();
    await vi.waitFor(() => expect(document.body.textContent).toContain('skubata01'));
    expect(JSON.parse(fetchMock.mock.calls.at(-1)[1].body)).toEqual({ recipe: pitchingRecipe });
  });

  it('renders non-choice clarifications without inventing a strikeout heading', async () => {
    await mountApp(() =>
      response({
        kind: 'needs_clarification',
        question: 'What minimum at-bat sample should this batting-average leaderboard use?',
        choices: [],
        suggested_recipe: null,
        recipe: null,
        plan: null,
      }),
    );

    inputText('Ask Ground Ball', 'highest batting average in 1894');
    document.querySelector('.chat-composer').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));
    await vi.waitFor(() => expect(document.body.textContent).toContain('What minimum at-bat sample'));
    expect(document.body.textContent).not.toContain('Batting or pitching?');
  });

  it('discovers a raw field through GB navigation and executes it as a structured recipe', async () => {
    const rawRun = {
      ...rowsRun,
      recipe: {
        source: 'Batting',
        grain: 'raw_rows',
        selections: ['Batting.GIDP'],
        groupings: [],
        ordering: [],
        output: { kind: 'interactive_page', size: 100, offset: 0 },
        predicate: null,
        ranking: null,
        catalog_revision: 'published-query-catalog-v3',
      },
      rows: [{ 'Batting.GIDP': 12 }],
    };
    const fetchMock = await mountApp(() => response(rawRun));

    document.querySelector('[aria-label="Open application navigation"]').click();
    await tick();
    expect(document.activeElement.textContent).toContain('Query');
    expect(document.querySelector('[role="menu"]').textContent).toContain('Evidence');
    [...document.querySelectorAll('[role="menu"] button')]
      .find((button) => button.textContent.includes('Browse fields'))
      .click();
    await tick();
    expect(document.body.textContent).toContain('Batting.GIDP');

    document.querySelector('[aria-label="Use Batting.GIDP"]').click();
    await vi.waitFor(() => expect(document.body.textContent).toContain('12'));
    const submitted = JSON.parse(fetchMock.mock.calls.at(-1)[1].body);
    expect(submitted.recipe.selections).toEqual(['Batting.GIDP']);
    expect(submitted.recipe.grain).toBe('raw_rows');
  });
});

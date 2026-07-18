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
  output: { kind: 'interactive_page', size: 100, offset: 0 },
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
};

function response(payload, ok = true) {
  return Promise.resolve({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(payload) });
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

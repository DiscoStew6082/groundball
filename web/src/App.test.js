import { mount, tick } from 'svelte';
import { describe, expect, it, vi } from 'vitest';

import App from './App.svelte';

const publicCapabilities = {
  name: 'Ground Ball',
  mode: 'public',
  query: { enabled: true, answer_modes: ['stats_only'], conversation: true },
  llm: { enabled: false },
  architecture: { enabled: false, component_details: false },
  developer_tools: { enabled: false },
  history: 'browser_local',
};

const localCapabilities = {
  ...publicCapabilities,
  mode: 'local',
  query: { enabled: true, answer_modes: ['stats_only', 'llm_flavored'], conversation: true },
  llm: { enabled: true },
  architecture: { enabled: true, component_details: true },
  developer_tools: { enabled: true },
};

const architectureCatalog = {
  components: [
    { id: 'web-app', label: 'Svelte Web App', description: 'Browser interface', layer: 'api', test_status: 'pass' },
    { id: 'query-router', label: 'Query Router', description: 'Routes the question', layer: 'routing', test_status: 'pass' },
    { id: 'claim-verifier', label: 'Claim Verifier', description: 'Verifies claims', layer: 'verification', test_status: null },
    { id: 'duckdb', label: 'DuckDB', description: 'Queries baseball data', layer: 'data', test_status: 'pass' },
    { id: 'llm', label: 'Local LLM', description: 'Writes optional narration', layer: 'generation', test_status: null },
  ],
};

const queryAnswer = {
  status: 'completed',
  answer: 'Tommy Davis led MLB with 153 RBI in 1962.',
  intent: 'stat_query',
  rows: {
    headers: ['player', 'RBI'],
    data: [['Tommy Davis', 153]],
  },
  sources: [{ type: 'duckdb', label: '1962 RBI leaders' }],
  sql: 'SELECT player, RBI FROM batting ORDER BY RBI DESC',
  warnings: [],
  unsupported: false,
  unsupported_reason: null,
  metadata: { dataset_release: '2026-07-17' },
  conversation_turn: {
    question: 'who had the most RBIs in 1962',
    answer: { answer: 'Tommy Davis led MLB with 153 RBI in 1962.' },
  },
  architecture_trace: null,
};

function jsonResponse(payload, ok = true) {
  return Promise.resolve({
    ok,
    status: ok ? 200 : 500,
    json: () => Promise.resolve(payload),
  });
}

async function renderWithCapabilities(capabilities = publicCapabilities) {
  vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(jsonResponse(capabilities)));
  mount(App, { target: document.body });
  await vi.waitFor(() => {
    expect(document.body.textContent).toContain(
      capabilities.mode === 'public' ? 'Deterministic public demo' : 'Local almanac workspace',
    );
  });
}

async function submitQuestion(question = 'who had the most RBIs in 1962') {
  const input = document.querySelector('[aria-label="Baseball question"]');
  input.value = question;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  document.querySelector('form').dispatchEvent(new SubmitEvent('submit', { bubbles: true }));
  await tick();
}

describe('Ground Ball application', () => {
  it('uses capabilities as the only authority for hosted feature visibility', async () => {
    await renderWithCapabilities();

    expect(document.querySelector('h1').textContent).toBe('Ground Ball');
    expect(document.body.textContent).toContain('Deterministic public demo');
    expect(document.body.textContent).not.toContain('Architecture Explorer');
    expect(document.body.textContent).not.toContain('Developer Tools');
    expect(document.querySelector('[aria-label="Answer mode"]')).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).not.toHaveBeenCalledWith('/api/architecture');
    expect(document.querySelector('[aria-label="Baseball question"]').value).toBe(
      'who had the most RBIs in 1962',
    );
  });

  it('submits one self-contained request and renders answer-first evidence and history', async () => {
    let resolveQuery;
    const queryPromise = new Promise((resolve) => {
      resolveQuery = resolve;
    });
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse(publicCapabilities))
      .mockReturnValueOnce(queryPromise);
    vi.stubGlobal('fetch', fetchMock);
    mount(App, { target: document.body });
    await vi.waitFor(() => expect(document.body.textContent).toContain('Deterministic public demo'));

    await submitQuestion();
    expect(document.querySelector('button[type="submit"]').disabled).toBe(true);
    expect(document.querySelector('[data-testid="answer"]').textContent).toContain('Working');

    resolveQuery(await jsonResponse(queryAnswer));
    await vi.waitFor(() =>
      expect(document.querySelector('[data-testid="answer"]').textContent).toContain('153 RBI'),
    );

    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/query',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          question: 'who had the most RBIs in 1962',
          conversation: [],
          answer_mode: 'stats_only',
        }),
      }),
    );
    expect(document.querySelector('[data-testid="answer"]').textContent).toContain('153 RBI');
    expect(document.querySelector('[data-testid="results"]').textContent).toContain('Tommy Davis');
    expect(document.querySelector('[data-testid="evidence"]').textContent).toContain(
      '1962 RBI leaders',
    );
    expect(document.querySelector('[data-testid="sql"]').textContent).toContain('SELECT player');
    expect(document.querySelector('[data-testid="conversation"]').textContent).toContain(
      'who had the most RBIs in 1962',
    );
    expect(document.querySelector('[data-testid="conversation"]').textContent).toContain(
      'Tommy Davis led MLB',
    );
    expect(document.body.textContent).toContain('Recent questions');
    expect(JSON.parse(localStorage.getItem('ground-ball-history'))).toHaveLength(1);
    expect(document.body.textContent).toContain('Download CSV');
    expect(document.body.textContent).toContain('Download JSON');

    const nextInput = document.querySelector('[aria-label="Baseball question"]');
    nextInput.value = 'a different draft question';
    nextInput.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();
    const jsonLink = [...document.querySelectorAll('a')].find((link) =>
      link.textContent.includes('Download JSON'),
    );
    const exported = JSON.parse(decodeURIComponent(jsonLink.href.split(',')[1]));
    expect(exported.question).toBe('who had the most RBIs in 1962');
  });

  it('publishes only the newest response and turns request failures into visible errors', async () => {
    let resolveFirst;
    const first = new Promise((resolve) => {
      resolveFirst = resolve;
    });
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse(publicCapabilities))
      .mockReturnValueOnce(first)
      .mockReturnValueOnce(jsonResponse({ error: 'database unavailable' }, false));
    vi.stubGlobal('fetch', fetchMock);
    mount(App, { target: document.body });
    await vi.waitFor(() => expect(document.body.textContent).toContain('Deterministic public demo'));

    await submitQuestion('first question');
    await submitQuestion('second question');
    await vi.waitFor(() =>
      expect(document.querySelector('[role="alert"]').textContent).toContain('database unavailable'),
    );

    resolveFirst(await jsonResponse({ ...queryAnswer, answer: 'stale answer' }));
    await tick();
    await tick();
    expect(document.body.textContent).not.toContain('stale answer');
  });

  it('shows architecture and developer tools only in local mode', async () => {
    const traceAnswer = {
      ...queryAnswer,
      architecture_trace: {
        route: 'stat_query',
        total_ms: 6.4,
        stages: [
          { component_id: 'web', label: 'Web app', elapsed_ms: 1.2 },
          { component_id: 'duckdb', label: 'DuckDB', elapsed_ms: 5.2 },
        ],
      },
    };
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse(localCapabilities))
      .mockReturnValueOnce(jsonResponse(architectureCatalog))
      .mockReturnValueOnce(jsonResponse(traceAnswer))
      .mockReturnValueOnce(
        jsonResponse({
          component: {
            ...architectureCatalog.components[1],
            file_path: 'src/baseball_rag/routing/query_router.py',
          },
          source_excerpt: 'def route(question):\n    return decide(question)',
        }),
      )
      .mockReturnValueOnce(jsonResponse({ passed: 104, failed: 0, errors: 0, skipped: 2 }));
    vi.stubGlobal('fetch', fetchMock);
    mount(App, { target: document.body });
    await vi.waitFor(() => expect(document.body.textContent).toContain('Local almanac workspace'));
    await vi.waitFor(() => expect(fetchMock.mock.calls).toContainEqual(['/api/architecture']));
    await vi.waitFor(() =>
      expect(document.querySelector('[data-component-id="query-router"]')).not.toBeNull(),
    );

    const answerMode = document.querySelector('[aria-label="Answer mode"]');
    expect(answerMode.value).toBe('stats_only');
    answerMode.value = 'llm_flavored';
    answerMode.dispatchEvent(new Event('change', { bubbles: true }));
    await submitQuestion();
    await vi.waitFor(() => expect(document.body.textContent).toContain('DuckDB'));

    expect(document.body.textContent).toContain('Architecture Explorer');
    expect(document.body.textContent).toContain('API');
    expect(document.body.textContent).toContain('Routing');
    expect(document.body.textContent).toContain('Verification');
    expect(document.body.textContent).toContain('Data');
    expect(document.body.textContent).toContain('Generation');
    expect(document.body.textContent).toContain('DuckDB');
    expect(document.body.textContent).toContain('Developer Tools');
    expect(fetchMock).toHaveBeenCalledWith('/api/architecture');
    expect(JSON.parse(fetchMock.mock.calls[2][1].body).answer_mode).toBe('llm_flavored');

    document.querySelector('[data-component-id="query-router"]').click();
    await vi.waitFor(() => expect(document.body.textContent).toContain('query_router.py'));
    expect(fetchMock).toHaveBeenCalledWith('/api/architecture/query-router');
    expect(document.body.textContent).toContain('Routes the question');
    expect(document.body.textContent).toContain('def route(question)');
    expect(document.body.textContent).toContain('PASS');

    document.querySelector('[data-testid="run-tests"]').click();
    await vi.waitFor(() => expect(document.body.textContent).toContain('104 passed'));
    expect(fetchMock).toHaveBeenLastCalledWith('/api/developer/tests', { method: 'POST' });
    expect(document.body.textContent).toContain('104 passed');
  });

  it('keeps a successful answer visible when browser history storage fails', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => {
      throw new DOMException('quota exceeded');
    });
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse(publicCapabilities))
      .mockReturnValueOnce(jsonResponse(queryAnswer));
    vi.stubGlobal('fetch', fetchMock);
    mount(App, { target: document.body });
    await vi.waitFor(() => expect(document.body.textContent).toContain('Deterministic public demo'));

    await submitQuestion();

    await vi.waitFor(() =>
      expect(document.querySelector('[data-testid="answer"]').textContent).toContain('153 RBI'),
    );
    expect(document.querySelector('[role="alert"]')).toBeNull();
  });

  it('restores the matching conversation snapshot with a history result', async () => {
    const savedTurn = {
      question: 'career home run leaders',
      answer: { answer: 'Barry Bonds led with 762 home runs.' },
    };
    localStorage.setItem(
      'ground-ball-history',
      JSON.stringify([
        {
          question: 'career home run leaders',
          result: { ...queryAnswer, answer: 'Barry Bonds led with 762 home runs.' },
          conversation: [savedTurn],
          saved_at: '2026-07-17T00:00:00Z',
        },
      ]),
    );
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse(publicCapabilities))
      .mockReturnValueOnce(jsonResponse(queryAnswer));
    vi.stubGlobal('fetch', fetchMock);
    mount(App, { target: document.body });
    await vi.waitFor(() =>
      expect(document.querySelector('.history-list button')).not.toBeNull(),
    );

    [...document.querySelectorAll('.history-list button')][0].click();
    await tick();
    await submitQuestion('tell me about the first player');
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    expect(JSON.parse(fetchMock.mock.calls[1][1].body).conversation).toEqual([savedTurn]);
  });

  it('keeps restored conversation snapshots within the server request limit', async () => {
    const savedTurns = Array.from({ length: 21 }, (_, index) => ({
      question: `question ${index}`,
      answer: { answer: `answer ${index}` },
    }));
    localStorage.setItem(
      'ground-ball-history',
      JSON.stringify([
        {
          question: 'career home run leaders',
          result: queryAnswer,
          conversation: savedTurns,
          saved_at: '2026-07-17T00:00:00Z',
        },
      ]),
    );
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse(publicCapabilities))
      .mockReturnValueOnce(jsonResponse(queryAnswer));
    vi.stubGlobal('fetch', fetchMock);
    mount(App, { target: document.body });
    await vi.waitFor(() =>
      expect(document.querySelector('.history-list button')).not.toBeNull(),
    );

    document.querySelector('.history-list button').click();
    await submitQuestion('tell me about the leader');
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const submittedConversation = JSON.parse(fetchMock.mock.calls[1][1].body).conversation;
    expect(submittedConversation).toHaveLength(20);
    expect(submittedConversation[0].question).toBe('question 1');
  });
});

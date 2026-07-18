<script>
  import { onMount } from 'svelte';

  import { csvDataUrl, jsonDataUrl, tableRows } from './lib/downloads.js';

  const DEFAULT_QUESTION = 'who had the most RBIs in 1962';
  const EXAMPLES = [
    DEFAULT_QUESTION,
    'career home run leaders',
    'who won the Triple Crown and which years',
    'what is OPS',
    'who played for the Braves in 1936',
  ];
  const HISTORY_KEY = 'ground-ball-history';
  const MAX_HISTORY = 12;
  const MAX_CONVERSATION_TURNS = 20;
  const ARCHITECTURE_LAYERS = [
    ['api', 'API'],
    ['routing', 'Routing'],
    ['verification', 'Verification'],
    ['data', 'Data'],
    ['generation', 'Generation'],
  ];
  const prototypeVariant = new URLSearchParams(window.location.search).get('variant');
  const prototypeMode = import.meta.env.DEV && ['A', 'B', 'C'].includes(prototypeVariant);

  let capabilities = null;
  let capabilityError = '';
  let question = DEFAULT_QUESTION;
  let pending = false;
  let result = null;
  let resultQuestion = '';
  let error = '';
  let conversation = [];
  let history = [];
  let answerMode = 'stats_only';
  let requestSequence = 0;
  let architectureComponents = [];
  let architectureError = '';
  let selectedComponent = null;
  let componentPending = false;
  let testsPending = false;
  let testsResult = null;
  let testsError = '';
  let PrototypeComponent = null;

  $: table = tableRows(result?.rows);
  $: queryEnabled = capabilityEnabled(capabilities?.query);
  $: llmEnabled = capabilityEnabled(capabilities?.llm);
  $: architectureEnabled =
    capabilities?.mode === 'local' && capabilityEnabled(capabilities?.architecture);
  $: developerToolsEnabled = capabilityEnabled(capabilities?.developer_tools);
  $: historyEnabled = capabilities?.history === 'browser_local' || capabilities?.history === true;
  $: answerModes = capabilities?.query?.answer_modes ??
    (llmEnabled ? ['stats_only', 'llm_flavored'] : ['stats_only']);
  $: architectureByLayer = Object.fromEntries(
    ARCHITECTURE_LAYERS.map(([layerId]) => [
      layerId,
      architectureComponents.filter((component) => component.layer === layerId),
    ]),
  );
  $: exportPayload = result
    ? {
        question: resultQuestion,
        status: result.status,
        answer: result.answer,
        intent: result.intent,
        rows: result.rows,
        sources: result.sources,
        sql: result.sql,
        warnings: result.warnings,
        unsupported: result.unsupported,
        unsupported_reason: result.unsupported_reason,
        metadata: result.metadata,
      }
    : null;

  onMount(async () => {
    if (prototypeMode) {
      PrototypeComponent = (
        await import('./prototypes/query-recipe/MobileQueryRecipePrototype.svelte')
      ).default;
    }
    history = readHistory();
    try {
      const response = await fetch('/api/capabilities');
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Could not load application capabilities.');
      capabilities = payload;
      if (localArchitectureEnabled(payload)) await loadArchitecture();
    } catch (caught) {
      capabilityError = messageFrom(caught, 'Could not start Ground Ball.');
    }
  });

  function readHistory() {
    try {
      const stored = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
      return Array.isArray(stored) ? stored.slice(0, MAX_HISTORY) : [];
    } catch {
      return [];
    }
  }

  function saveHistory(entry) {
    history = [entry, ...history.filter((item) => item.question !== entry.question)].slice(
      0,
      MAX_HISTORY,
    );
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
    } catch {
      // Browser storage is optional; a completed query must remain successful.
    }
  }

  function chooseExample(example) {
    question = example;
  }

  function restoreHistory(item) {
    question = item.question;
    result = item.result;
    resultQuestion = item.question;
    conversation = Array.isArray(item.conversation)
      ? item.conversation.slice(-MAX_CONVERSATION_TURNS)
      : [];
    error = '';
  }

  function capabilityEnabled(capability) {
    if (capability && typeof capability === 'object') return capability.enabled === true;
    return capability === true;
  }

  function localArchitectureEnabled(payload) {
    return payload?.mode === 'local' && capabilityEnabled(payload?.architecture);
  }

  async function loadArchitecture() {
    architectureError = '';
    try {
      const response = await fetch('/api/architecture');
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || payload.detail || 'Architecture is unavailable.');
      architectureComponents = payload.components ?? [];
    } catch (caught) {
      architectureError = messageFrom(caught, 'Architecture is unavailable.');
    }
  }

  async function inspectComponent(componentId) {
    if (!architectureEnabled || componentPending) return;
    componentPending = true;
    architectureError = '';
    try {
      const response = await fetch(`/api/architecture/${encodeURIComponent(componentId)}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || payload.detail || 'Component detail is unavailable.');
      selectedComponent = payload;
    } catch (caught) {
      architectureError = messageFrom(caught, 'Component detail is unavailable.');
    } finally {
      componentPending = false;
    }
  }

  async function submitQuery() {
    const submitted = question.trim();
    if (!submitted || !queryEnabled) return;

    const sequence = ++requestSequence;
    pending = true;
    result = null;
    error = '';

    try {
      const response = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: submitted,
          conversation,
          answer_mode: answerMode,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || payload.detail || `Request failed (${response.status}).`);
      if (sequence !== requestSequence) return;

      result = payload;
      question = submitted;
      resultQuestion = submitted;
      const nextConversation = payload.conversation_turn
        ? [...conversation, payload.conversation_turn].slice(-MAX_CONVERSATION_TURNS)
        : conversation;
      conversation = nextConversation;
      if (historyEnabled) {
        saveHistory({
          question: submitted,
          result: payload,
          conversation: nextConversation,
          saved_at: new Date().toISOString(),
        });
      }
    } catch (caught) {
      if (sequence !== requestSequence) return;
      error = messageFrom(caught, 'Ground Ball could not return an answer.');
    } finally {
      if (sequence === requestSequence) pending = false;
    }
  }

  async function runTests() {
    if (!developerToolsEnabled || testsPending) return;
    testsPending = true;
    testsResult = null;
    testsError = '';
    try {
      const response = await fetch('/api/developer/tests', { method: 'POST' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Tests could not run.');
      testsResult = payload;
    } catch (caught) {
      testsError = messageFrom(caught, 'Tests could not run.');
    } finally {
      testsPending = false;
    }
  }

  function messageFrom(caught, fallback) {
    return caught instanceof Error && caught.message ? caught.message : fallback;
  }

  function conversationAnswer(turn) {
    if (typeof turn?.answer === 'string') return turn.answer;
    return turn?.answer?.answer ?? '';
  }
</script>

<svelte:head>
  <title>Ground Ball</title>
</svelte:head>

<main class="desktop-shell">
  <section class="app-window" aria-label="Ground Ball application window">
    <header class="title-bar">
      <div class="app-identity">
        <span class="ball-mark" aria-hidden="true">GB</span>
        <div>
          <h1>{capabilities?.name ?? 'Ground Ball'}</h1>
          <p>
            {#if capabilities?.mode === 'public'}
              Deterministic public demo
            {:else if capabilities?.mode === 'local'}
              Local almanac workspace
            {:else}
              Modern baseball almanac
            {/if}
          </p>
        </div>
      </div>
      <div class="window-controls" aria-hidden="true">
        <span>—</span><span>□</span><span>×</span>
      </div>
    </header>

    {#if capabilityError}
      <div class="startup-error" role="alert">{capabilityError}</div>
    {:else}
      <div class="workspace">
        <aside class="sidebar">
          <div class="brand-block">
            <span class="eyebrow">Historical MLB</span>
            <strong>Ask the record.</strong>
            <p>Grounded answers backed by inspectable data.</p>
          </div>

          <nav aria-label="Application sections">
            <a class="nav-item active" href="#query">Query</a>
            <a class="nav-item" href="#evidence">Evidence</a>
            {#if historyEnabled}
              <a class="nav-item" href="#history">History</a>
            {/if}
            {#if architectureEnabled}
              <a class="nav-item" href="#architecture">Architecture</a>
            {/if}
          </nav>

          <div class="runtime-card">
            <span class:online={capabilities} class="status-dot"></span>
            <div>
              <strong>{capabilities ? 'Ready' : 'Connecting'}</strong>
              <small>{llmEnabled ? 'Local narration enabled' : 'No LLM access'}</small>
            </div>
          </div>
        </aside>

        <div class:prototype-column={prototypeMode} class="main-column">
          {#if prototypeMode}
            {#if PrototypeComponent}
              <PrototypeComponent />
            {:else}
              <p class="empty-copy">Loading mobile prototype…</p>
            {/if}
          {:else}
          <section class="query-composer" id="query">
            <div class="section-heading">
              <div>
                <span class="eyebrow">Natural language in</span>
                <h2>What do you want to know?</h2>
              </div>
              <span class="mode-badge">{capabilities?.mode ?? 'loading'}</span>
            </div>

            <form on:submit|preventDefault={submitQuery}>
              <label for="baseball-question">Baseball question</label>
              {#if llmEnabled}
                <div class="answer-mode-row">
                  <label for="answer-mode">Answer mode</label>
                  <select id="answer-mode" aria-label="Answer mode" bind:value={answerMode}>
                    {#each answerModes as mode}
                      <option value={mode}>{mode === 'stats_only' ? 'Stats only' : 'LLM-flavored narration'}</option>
                    {/each}
                  </select>
                </div>
              {/if}
              <div class="query-input-row">
                <input
                  id="baseball-question"
                  aria-label="Baseball question"
                  bind:value={question}
                  autocomplete="off"
                  spellcheck="true"
                />
                <button type="submit" class="ask-button" disabled={pending || !queryEnabled}>
                  {pending ? 'Working…' : 'Ask'}
                </button>
              </div>
            </form>

            <div class="examples" aria-label="Example questions">
              {#each EXAMPLES as example}
                <button type="button" on:click={() => chooseExample(example)}>{example}</button>
              {/each}
            </div>
          </section>

          <section class="answer-card" data-testid="answer" aria-live="polite">
            <div class="card-kicker">
              <span>Answer</span>
              {#if result?.intent}<span class="intent-chip">{result.intent}</span>{/if}
            </div>
            {#if pending}
              <div class="working-state"><span class="spinner"></span> Working through the record…</div>
            {:else if error}
              <div class="answer-error" role="alert">{error}</div>
            {:else if result}
              <p class="answer-copy">{result.answer}</p>
              {#if result.unsupported}
                <p class="support-state">Unsupported: {result.unsupported_reason ?? 'unsupported'}</p>
              {/if}
              {#if result.warnings?.length}
                <ul class="warnings">
                  {#each result.warnings as warning}<li>{warning}</li>{/each}
                </ul>
              {/if}
            {:else}
              <p class="empty-copy">Ask a question to see the answer, evidence, and query details.</p>
            {/if}
          </section>

          {#if conversation.length}
            <section class="conversation-card" data-testid="conversation">
              <div class="card-kicker"><span>Conversation</span><span>{conversation.length} turns</span></div>
              <div class="conversation-list">
                {#each conversation as turn}
                  <div class="conversation-turn">
                    <p><span>You</span>{turn.question}</p>
                    <p><span>Ground Ball</span>{conversationAnswer(turn)}</p>
                  </div>
                {/each}
              </div>
            </section>
          {/if}

          {#if result}
            <section class="results-card" data-testid="results">
              <div class="card-kicker"><span>Key rows</span><span>{table.data.length} shown</span></div>
              {#if table.headers.length}
                <div class="table-scroll">
                  <table>
                    <thead><tr>{#each table.headers as header}<th>{header}</th>{/each}</tr></thead>
                    <tbody>
                      {#each table.data as row}
                        <tr>{#each row as cell}<td>{cell ?? '—'}</td>{/each}</tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              {:else}
                <p class="empty-copy">This answer did not return tabular rows.</p>
              {/if}
            </section>

            <section class="evidence-card" id="evidence">
              <div class="card-kicker"><span>Evidence</span><span>Audit-ready detail</span></div>
              <div class="disclosures">
                <details open data-testid="evidence">
                  <summary>Sources <span>{result.sources?.length ?? 0}</span></summary>
                  <pre>{JSON.stringify(result.sources ?? [], null, 2)}</pre>
                </details>
                <details data-testid="sql">
                  <summary>SQL or query plan</summary>
                  <pre>{result.sql || 'No SQL was produced for this answer.'}</pre>
                </details>
                <details>
                  <summary>Dataset release</summary>
                  <pre>{JSON.stringify(result.metadata ?? {}, null, 2)}</pre>
                </details>
              </div>
              <div class="download-row">
                <a href={csvDataUrl(result.rows)} download="ground-ball-result.csv">Download CSV</a>
                <a href={jsonDataUrl(exportPayload)} download="ground-ball-result.json">Download JSON</a>
              </div>
            </section>
          {/if}

          {#if architectureEnabled}
            <section class="architecture-card" id="architecture">
              <div class="card-kicker"><span>Architecture Explorer</span><span>Local only</span></div>
              {#if architectureError}<p class="answer-error" role="alert">{architectureError}</p>{/if}
              <div class="architecture-catalog">
                {#each ARCHITECTURE_LAYERS as [layerId, layerLabel]}
                  <section class="architecture-layer">
                    <h3>{layerLabel}</h3>
                    <div class="component-grid">
                      {#each architectureByLayer[layerId] ?? [] as component}
                        <button
                          type="button"
                          data-component-id={component.id}
                          class:selected={selectedComponent?.component?.id === component.id}
                          on:click={() => inspectComponent(component.id)}
                        >
                          <span>{component.label}</span>
                          <small>{component.test_status?.toUpperCase() ?? 'UNKNOWN'}</small>
                        </button>
                      {/each}
                    </div>
                  </section>
                {/each}
              </div>

              {#if selectedComponent}
                <aside class="component-detail" aria-live="polite">
                  <div class="component-detail-heading">
                    <div><span class="eyebrow">Runtime role</span><h3>{selectedComponent.component.label}</h3></div>
                    <span class="test-badge status-{selectedComponent.component.test_status ?? 'unknown'}">
                      {selectedComponent.component.test_status?.toUpperCase() ?? 'UNKNOWN'}
                    </span>
                  </div>
                  <p>{selectedComponent.component.description}</p>
                  <dl><dt>File path</dt><dd>{selectedComponent.component.file_path}</dd></dl>
                  <pre>{selectedComponent.source_excerpt || 'Source excerpt is unavailable.'}</pre>
                </aside>
              {/if}

              <div class="trace-heading"><span class="eyebrow">Latest query trace</span></div>
              {#if result?.architecture_trace}
                <div class="trace-summary">
                  <strong>{result.architecture_trace.route ?? result.intent}</strong>
                  {#if result.architecture_trace.total_ms != null}
                    <span>{result.architecture_trace.total_ms}ms total</span>
                  {/if}
                </div>
                <ol class="trace-path">
                  {#each result.architecture_trace.stages ?? [] as stage}
                    <li class:error-stage={stage.error}>
                      <span class="stage-index"></span>
                      <div><strong>{stage.label ?? stage.component_id}</strong><small>{stage.component_id}</small></div>
                      <span>{stage.elapsed_ms ?? 0}ms</span>
                    </li>
                  {/each}
                </ol>
              {:else}
                <p class="empty-copy">Run a query to inspect its execution path.</p>
              {/if}
            </section>
          {/if}

          {#if developerToolsEnabled}
            <details class="developer-card">
              <summary>Developer Tools <span>Local only</span></summary>
              <div class="developer-body">
                <button data-testid="run-tests" type="button" on:click={runTests} disabled={testsPending}>
                  {testsPending ? 'Tests are running…' : 'Run all tests'}
                </button>
                {#if testsResult}
                  <p>{testsResult.passed} passed · {testsResult.failed} failed · {testsResult.errors} errors · {testsResult.skipped} skipped</p>
                {/if}
                {#if testsError}<p class="answer-error" role="alert">{testsError}</p>{/if}
              </div>
            </details>
          {/if}
          {/if}
        </div>

        {#if historyEnabled}
          <aside class="history-panel" id="history">
            <div class="card-kicker"><span>Recent questions</span><span>On this device</span></div>
            {#if history.length}
              <div class="history-list">
                {#each history as item}
                  <button type="button" on:click={() => restoreHistory(item)}>
                    <span>{item.question}</span>
                    <small>{item.result?.intent ?? 'query'}</small>
                  </button>
                {/each}
              </div>
            {:else}
              <p class="empty-copy">Your latest results will stay here in this browser.</p>
            {/if}
          </aside>
        {/if}
      </div>
    {/if}
  </section>
</main>

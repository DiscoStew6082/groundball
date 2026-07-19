<script>
  import { onMount, tick } from 'svelte';

  import ChatComposer from './lib/ChatComposer.svelte';
  import DetailsSheet from './lib/DetailsSheet.svelte';
  import NavigationMenu from './lib/NavigationMenu.svelte';

  const HISTORY_KEY = 'ground-ball-query-history';
  const DEFAULT_QUESTION = '40-40';

  class HttpOutcomeError extends Error {
    constructor(outcome, status) {
      super(outcome?.detail || outcome?.error || `Request failed (${status}).`);
      this.outcome = outcome;
    }
  }

  let capabilities;
  let catalog = { sources: [], fields: [], values: [], relationships: [] };
  let draft = DEFAULT_QUESTION;
  let pending = false;
  let lastCompletedRun = null;
  let attemptOutcome = null;
  let submittedQuestion = '';
  let completedQuestion = '';
  let error = '';
  let navOpen = false;
  let navButton;
  let activeSurface = 'Query';
  let detailsOpen = false;
  let detailsButton;
  let fieldSearch = '';
  let fieldSource = '';
  let history = [];

  $: recipeText = lastCompletedRun?.recipe ? JSON.stringify(lastCompletedRun.recipe, null, 2) : '';
  $: visibleFields = catalog.fields.filter((field) =>
    (!fieldSource || field.source === fieldSource) &&
    (!fieldSearch || `${field.identity} ${field.column}`.toLowerCase().includes(fieldSearch.toLowerCase()))
  );

  onMount(async () => {
    history = readHistory();
    try {
      const [capabilityResponse, catalogResponse] = await Promise.all([
        fetch('/api/capabilities'),
        fetch('/api/query-catalog'),
      ]);
      capabilities = await readResponse(capabilityResponse);
      catalog = await readResponse(catalogResponse);
    } catch (caught) {
      error = messageFrom(caught, 'Ground Ball could not start.');
    }
  });

  function readHistory() {
    try {
      const stored = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
      return Array.isArray(stored) ? stored.slice(0, 12) : [];
    } catch {
      return [];
    }
  }

  function saveHistory(run, question) {
    const entry = { question, recipe: run.recipe, run, saved_at: new Date().toISOString() };
    history = [entry, ...history].slice(0, 12);
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
    } catch {
      // Query completion does not depend on optional browser storage.
    }
  }

  async function runQuestion(question) {
    if (pending) return;
    submittedQuestion = question;
    await runRequest({ question });
  }

  async function runRecipe(recipe) {
    if (pending) return;
    await runRequest({ recipe });
  }

  async function runRecipeText(text) {
    try {
      await runRecipe(JSON.parse(text));
      detailsOpen = false;
    } catch (caught) {
      error = messageFrom(caught, 'The structured recipe is not valid JSON.');
    }
  }

  async function runRequest(body) {
    if (pending) return;
    const endpoint = capabilities?.query?.endpoint ?? '/api/query-runs';
    activeSurface = 'Query';
    pending = true;
    attemptOutcome = null;
    error = '';
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const payload = await readResponse(response);
      if (['rows', 'no_data'].includes(payload.kind)) {
        lastCompletedRun = payload;
        completedQuestion = submittedQuestion;
        attemptOutcome = null;
        saveHistory(payload, completedQuestion);
      } else {
        attemptOutcome = payload;
      }
    } catch (caught) {
      if (caught instanceof HttpOutcomeError && caught.outcome && typeof caught.outcome === 'object') {
        attemptOutcome = {
          ...caught.outcome,
          kind: caught.outcome.kind ?? caught.outcome.error ?? 'failed',
        };
      } else {
        attemptOutcome = {
          kind: 'malformed',
          detail: messageFrom(caught, 'Ground Ball returned a malformed response.'),
        };
      }
    } finally {
      pending = false;
    }
  }

  async function readResponse(response) {
    const payload = await response.json();
    if (!response.ok) throw new HttpOutcomeError(payload, response.status);
    if (!payload || typeof payload !== 'object') {
      throw new Error('Ground Ball returned a malformed response.');
    }
    return payload;
  }

  function messageFrom(caught, fallback) {
    return caught instanceof Error && caught.message ? caught.message : fallback;
  }

  async function closeNavigation() {
    navOpen = false;
    await tick();
    navButton?.focus({ preventScroll: true });
  }

  async function closeDetails() {
    detailsOpen = false;
    await tick();
    detailsButton?.focus({ preventScroll: true });
  }

  function selectSurface(surface) {
    activeSurface = surface;
    closeNavigation();
  }

  function browseFromDetails() {
    detailsOpen = false;
    activeSurface = 'Browse fields';
  }

  function useField(field) {
    submittedQuestion = `Raw ${field.identity}`;
    runRecipe({
      catalog_revision: catalog.catalog_revision,
      source: field.source,
      grain: 'raw_rows',
      selections: [field.identity],
      predicate: null,
      groupings: [],
      ranking: null,
      ordering: [],
      output: {
        kind: 'interactive_page',
        size: capabilities?.mode === 'public' ? 25 : 100,
        offset: 0,
      },
    });
  }

  function restoreHistory(entry) {
    lastCompletedRun = entry.run;
    completedQuestion = entry.question;
    submittedQuestion = entry.question;
    attemptOutcome = null;
    activeSurface = 'Query';
  }

  function runPage(size, offset) {
    if (!lastCompletedRun?.recipe || pending) return;
    const pageRecipe = structuredClone(lastCompletedRun.recipe);
    pageRecipe.output = { kind: 'interactive_page', size, offset };
    runRecipe(pageRecipe);
  }

  function changePageSize(event) {
    runPage(Number(event.currentTarget.value), 0);
  }

  async function exportResult(format) {
    if (!lastCompletedRun?.recipe || pending) return;
    const exportRecipe = structuredClone(lastCompletedRun.recipe);
    exportRecipe.output = { kind: 'export', format };
    pending = true;
    error = '';
    try {
      const response = await fetch(capabilities?.query?.endpoint ?? '/api/query-runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe: exportRecipe }),
      });
      const exported = await readResponse(response);
      if (exported.kind !== 'exported') throw new Error('The export run did not return an export.');
      const blob = new Blob([exported.export.content], {
        type: format === 'csv' ? 'text/csv;charset=utf-8' : 'application/json;charset=utf-8',
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `ground-ball-query.${format}`;
      link.click();
      URL.revokeObjectURL(url);
      attemptOutcome = null;
    } catch (caught) {
      if (caught instanceof HttpOutcomeError && caught.outcome && typeof caught.outcome === 'object') {
        attemptOutcome = {
          ...caught.outcome,
          kind: caught.outcome.kind ?? caught.outcome.error ?? 'failed',
        };
      } else {
        attemptOutcome = {
          kind: 'malformed',
          detail: messageFrom(caught, 'Ground Ball could not export that result.'),
        };
      }
      activeSurface = 'Query';
      detailsOpen = false;
      await tick();
      detailsButton?.focus({ preventScroll: true });
    } finally {
      pending = false;
    }
  }

  function outcomeTitle(run) {
    if (!run) return '';
    const kind = run.kind ?? run.error;
    if (kind === 'rows' && run.pagination) return `${run.returned_row_count} rows returned`;
    if (kind === 'rows') return `${run.rows.length} matching rows`;
    if (kind === 'no_data') return 'No matching rows';
    if (kind === 'needs_clarification') return 'One detail needed';
    if (kind === 'rejected' || kind === 'unsupported') return 'That query is not published';
    if (kind === 'busy') return 'Ground Ball is busy';
    if (kind === 'rate_limited') return 'Query rate limit reached';
    if (kind === 'timed_out') return 'Query timed out';
    if (kind === 'export_too_large') return 'Complete export refused';
    if (kind === 'allowance_paused') return 'Public allowance paused';
    if (kind === 'provider_unavailable' || kind === 'unavailable') return 'Query unavailable';
    if (kind === 'malformed') return 'Malformed response';
    if (kind === 'failed') return 'Query failed';
    return 'Query result';
  }
</script>

<svelte:head><title>Ground Ball</title></svelte:head>

<main class="desktop-shell">
  <section class="app-window" aria-label="Ground Ball application window">
    <header class="title-bar">
      <div class="app-identity">
        <button
          bind:this={navButton}
          class="navigation-trigger"
          type="button"
          aria-label="Open application navigation"
          aria-expanded={navOpen}
          on:click={() => (navOpen = !navOpen)}
        ><span class="ball-mark" aria-hidden="true">GB</span></button>
        <div><h1>Ground Ball</h1><p>Historical MLB · deterministic query system</p></div>
      </div>
      <span class="runtime-status">{capabilities ? 'Ready' : 'Connecting'}</span>
    </header>

    {#if navOpen}
      <NavigationMenu active={activeSurface} onSelect={selectSurface} onClose={closeNavigation} />
    {/if}

    <div class="answer-workspace">
      {#if activeSurface === 'Browse fields'}
        <section class="catalog-browser">
          <small>QUERY CATALOG</small><h2>Browse fields</h2>
          <p>Raw source fields and reviewed promoted values share this catalog revision.</p>
          <div class="catalog-filters">
            <select bind:value={fieldSource} aria-label="Field source">
              <option value="">All sources</option>
              {#each catalog.sources as source}<option value={source.identity}>{source.identity}</option>{/each}
            </select>
            <input bind:value={fieldSearch} aria-label="Search fields" placeholder="Search fields" />
          </div>
          <div class="field-list">
            {#each visibleFields as field}
              <article>
                <div><strong>{field.identity}</strong><small>{field.data_type} · {field.operations.join(' · ')}</small></div>
                <button type="button" aria-label={`Use ${field.identity}`} on:click={() => useField(field)}>Use field</button>
              </article>
            {/each}
          </div>
          <h3>Promoted values</h3>
          <div class="field-list promoted-list">
            {#each catalog.values as value}
              <article><div><strong>{value.friendly_name}</strong><small>{value.identity}{value.formula ? ` · ${value.formula}` : ''}</small></div></article>
            {/each}
          </div>
        </section>
      {:else if activeSurface === 'Evidence'}
        <section class="evidence-surface">
          <small>LAST QUERY RUN</small><h2>Evidence</h2>
          {#if lastCompletedRun?.evidence}
            <dl>
              <dt>Catalog</dt><dd>{lastCompletedRun.evidence.catalog_revision}</dd>
              <dt>Data release</dt><dd>{lastCompletedRun.evidence.data_release}</dd>
              <dt>Matched rows</dt><dd>{lastCompletedRun.evidence.matched_row_count}</dd>
              <dt>Fingerprint</dt><dd>{lastCompletedRun.evidence.result_fingerprint}</dd>
            </dl>
            <button bind:this={detailsButton} type="button" aria-label="Open query details" on:click={() => (detailsOpen = true)}>Open full Details</button>
          {:else}<p>Run a query to inspect its plan, rows, calculations, sources, and SQL.</p>{/if}
        </section>
      {:else if activeSurface === 'History'}
        <section class="history-surface">
          <small>LOCAL HISTORY</small><h2>Query snapshots</h2>
          {#if history.length}
            {#each history as entry}
              <button type="button" on:click={() => restoreHistory(entry)}><strong>{entry.question || entry.recipe.source}</strong><small>{entry.saved_at}</small></button>
            {/each}
          {:else}<p>No saved Query Runs yet.</p>{/if}
        </section>
      {:else if activeSurface === 'Architecture'}
        <section class="architecture-surface">
          <small>COMPOSITION ROOT</small><h2>One deterministic query path</h2>
          <p>Natural language and structured edits produce the same Query Recipe, canonical Query Plan, immutable Query Run, and evidence.</p>
          <code>Query Recipe → prepare → Query Plan → execute → Query Run</code>
        </section>
      {:else}
        <article class="answer-feed">
          {#if !lastCompletedRun && !attemptOutcome && !pending}
            <section class="feed-welcome">
              <span class="welcome-mark" aria-hidden="true">GB</span>
              <h2>Ask the record.</h2>
              <p>Edit the 40-40 example in the composer, browse any published raw field, or ask a reviewed baseball question.</p>
            </section>
          {/if}

          {#if pending}
            <section class:compact={lastCompletedRun} class="working-state" aria-live="polite"><span></span><p>Planning and checking the record…</p></section>
          {/if}

          {#if attemptOutcome?.kind === 'needs_clarification'}
            <section class="clarification-card" aria-live="polite">
              <small>CLARIFICATION</small><h2>{attemptOutcome.question}</h2>
              <div>{#each attemptOutcome.choices ?? [] as choice}<button class="clarification-choice" type="button" disabled={pending} on:click={() => runRecipe(choice.recipe)}>{choice.label}</button>{/each}</div>
              {#if attemptOutcome.suggested_recipe}<button class="clarification-choice" type="button" disabled={pending} on:click={() => runRecipe(attemptOutcome.suggested_recipe)}>Use suggested recipe</button>{/if}
            </section>
          {/if}

          {#if attemptOutcome && attemptOutcome.kind !== 'needs_clarification'}
            <section class="run-card problem attempt-outcome" aria-label="Latest attempt" aria-live="polite">
              <small>LATEST ATTEMPT</small><h2>{outcomeTitle(attemptOutcome)}</h2>
              {#if attemptOutcome.detail}<p>{attemptOutcome.detail}</p>{/if}
              {#if attemptOutcome.retry_at && !attemptOutcome.detail?.includes(attemptOutcome.retry_at)}<p>Retry at {attemptOutcome.retry_at}.</p>{/if}
              {#if attemptOutcome.guidance}<p>{attemptOutcome.guidance}</p>{/if}
              {#if attemptOutcome.reason}<p>{attemptOutcome.reason}</p>{/if}
            </section>
          {/if}

          {#if lastCompletedRun}
            <section class="run-card" aria-label="Completed query result" aria-live="polite">
              {#if completedQuestion}<p class="feed-question">{completedQuestion}</p>{/if}
              <small>{lastCompletedRun.kind.replaceAll('_', ' ')}</small><h2>{outcomeTitle(lastCompletedRun)}</h2>
              {#if lastCompletedRun.reason}<p>{lastCompletedRun.reason}</p>{/if}
              {#if lastCompletedRun.pagination}
                <p class="result-count">returned {lastCompletedRun.returned_row_count} of {lastCompletedRun.total_matched_count} matched</p>
                <div class="pagination-controls" aria-label="Result pagination">
                  <label>Rows per page
                    <select aria-label="Rows per page" value={lastCompletedRun.pagination.size} disabled={pending} on:change={changePageSize}>
                      <option value="25">25</option><option value="50">50</option><option value="100">100</option>
                    </select>
                  </label>
                  <div>
                    <button type="button" aria-label="Previous page" disabled={pending || lastCompletedRun.pagination.offset === 0} on:click={() => runPage(lastCompletedRun.pagination.size, Math.max(0, lastCompletedRun.pagination.offset - lastCompletedRun.pagination.size))}>Previous</button>
                    <button type="button" aria-label="Next page" disabled={pending || !lastCompletedRun.pagination.has_more} on:click={() => runPage(lastCompletedRun.pagination.size, lastCompletedRun.pagination.offset + lastCompletedRun.pagination.size)}>Next</button>
                  </div>
                </div>
              {/if}
              {#if lastCompletedRun.rows?.length}
                <div class="result-scroller" data-testid="results">
                  <table><thead><tr>{#each Object.keys(lastCompletedRun.rows[0]) as key}<th>{key}</th>{/each}</tr></thead>
                    <tbody>{#each lastCompletedRun.rows as row}<tr>{#each Object.values(row) as value}<td>{value ?? '—'}</td>{/each}</tr>{/each}</tbody>
                  </table>
                </div>
              {/if}
              {#if lastCompletedRun.plan}
                <button bind:this={detailsButton} class="details-link" type="button" aria-label="Open query details" on:click={() => (detailsOpen = true)}>Details ›</button>
              {/if}
            </section>
          {/if}

          {#if error}<div class="inline-error" role="alert">{error}</div>{/if}
        </article>
      {/if}
    </div>

    <div class="composer-dock"><ChatComposer bind:value={draft} {pending} onSubmit={runQuestion} /></div>
  </section>
</main>

{#if detailsOpen && lastCompletedRun}
  <DetailsSheet result={lastCompletedRun} {recipeText} {pending} onClose={closeDetails} onRunRecipe={runRecipeText} onExport={exportResult} onBrowseFields={browseFromDetails} />
{/if}

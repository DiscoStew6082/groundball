<script>
  import { onMount, tick } from 'svelte';

  import ChatComposer from './lib/ChatComposer.svelte';
  import DetailsSheet from './lib/DetailsSheet.svelte';
  import NavigationMenu from './lib/NavigationMenu.svelte';

  const HISTORY_KEY = 'ground-ball-query-history';
  const DEFAULT_QUESTION = '40-40';

  let capabilities;
  let catalog = { sources: [], fields: [], values: [], relationships: [] };
  let draft = DEFAULT_QUESTION;
  let pending = false;
  let result = null;
  let submittedQuestion = '';
  let error = '';
  let navOpen = false;
  let navButton;
  let activeSurface = 'Query';
  let detailsOpen = false;
  let detailsButton;
  let fieldSearch = '';
  let fieldSource = '';
  let history = [];

  $: recipeText = result?.recipe ? JSON.stringify(result.recipe, null, 2) : '';
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

  function saveHistory(run) {
    const entry = { question: submittedQuestion, recipe: run.recipe, run, saved_at: new Date().toISOString() };
    history = [entry, ...history].slice(0, 12);
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
    } catch {
      // Query completion does not depend on optional browser storage.
    }
  }

  async function runQuestion(question) {
    submittedQuestion = question;
    await runRequest({ question });
  }

  async function runRecipe(recipe) {
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
    const endpoint = capabilities?.query?.endpoint ?? '/api/query-runs';
    pending = true;
    error = '';
    const requestResult = result;
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const payload = await readResponse(response);
      result = payload;
      activeSurface = 'Query';
      if (['rows', 'no_data'].includes(payload.kind)) saveHistory(payload);
    } catch (caught) {
      result = requestResult;
      error = messageFrom(caught, 'Ground Ball could not run that query.');
    } finally {
      pending = false;
    }
  }

  async function readResponse(response) {
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || payload.error || `Request failed (${response.status}).`);
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
      output: { kind: 'interactive_page', size: 100, offset: 0 },
    });
  }

  function restoreHistory(entry) {
    result = entry.run;
    submittedQuestion = entry.question;
    activeSurface = 'Query';
  }

  async function exportResult(format) {
    if (!result?.recipe) return;
    const exportRecipe = structuredClone(result.recipe);
    exportRecipe.output = { kind: 'export', format };
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
    } catch (caught) {
      error = messageFrom(caught, 'Ground Ball could not export that result.');
    }
  }

  function outcomeTitle(run) {
    if (!run) return '';
    if (run.kind === 'rows') return `${run.rows.length} matching rows`;
    if (run.kind === 'no_data') return 'No matching rows';
    if (run.kind === 'needs_clarification') return 'One detail needed';
    if (run.kind === 'rejected') return 'That query is not published';
    if (run.kind === 'unavailable') return 'Query unavailable';
    if (run.kind === 'failed') return 'Query failed';
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
          {#if result?.evidence}
            <dl>
              <dt>Catalog</dt><dd>{result.evidence.catalog_revision}</dd>
              <dt>Data release</dt><dd>{result.evidence.data_release}</dd>
              <dt>Matched rows</dt><dd>{result.evidence.matched_row_count}</dd>
              <dt>Fingerprint</dt><dd>{result.evidence.result_fingerprint}</dd>
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
          {#if !result && !pending}
            <section class="feed-welcome">
              <span class="welcome-mark" aria-hidden="true">GB</span>
              <h2>Ask the record.</h2>
              <p>Edit the 40-40 example in the composer, browse any published raw field, or ask a reviewed baseball question.</p>
            </section>
          {:else if pending}
            <section class="working-state" aria-live="polite"><span></span><p>Planning and checking the record…</p></section>
          {:else if result?.kind === 'needs_clarification'}
            <section class="clarification-card" aria-live="polite">
              <small>CLARIFICATION</small><h2>{result.question}</h2>
              <div>{#each result.choices ?? [] as choice}<button class="clarification-choice" type="button" on:click={() => runRecipe(choice.recipe)}>{choice.label}</button>{/each}</div>
              {#if result.suggested_recipe}<button class="clarification-choice" type="button" on:click={() => runRecipe(result.suggested_recipe)}>Use suggested recipe</button>{/if}
            </section>
          {:else}
            <section class:problem={['rejected', 'unavailable', 'failed'].includes(result?.kind)} class="run-card" aria-live="polite">
              {#if submittedQuestion}<p class="feed-question">{submittedQuestion}</p>{/if}
              <small>{result?.kind?.replaceAll('_', ' ')}</small><h2>{outcomeTitle(result)}</h2>
              {#if result?.reason}<p>{result.reason}</p>{/if}
              {#if result?.rows?.length}
                <div class="result-scroller" data-testid="results">
                  <table><thead><tr>{#each Object.keys(result.rows[0]) as key}<th>{key}</th>{/each}</tr></thead>
                    <tbody>{#each result.rows as row}<tr>{#each Object.values(row) as value}<td>{value ?? '—'}</td>{/each}</tr>{/each}</tbody>
                  </table>
                </div>
              {/if}
              {#if result?.plan}
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

{#if detailsOpen && result}
  <DetailsSheet {result} {recipeText} onClose={closeDetails} onRunRecipe={runRecipeText} onExport={exportResult} onBrowseFields={browseFromDetails} />
{/if}

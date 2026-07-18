<script>
  import {
    CLARIFICATION_QUESTION,
    EXAMPLE_QUESTION,
    FIELD_GROUPS,
    RECIPE,
    RESULTS,
  } from './fixtures.js';

  export let previewState = 'example';
  export let setPreviewState = () => {};

  let view = previewState === 'results' ? 'results' : 'build';
  let priorPreviewState = previewState;
  let question = EXAMPLE_QUESTION;

  $: if (previewState !== priorPreviewState) {
    view = previewState === 'results' ? 'results' : 'build';
    priorPreviewState = previewState;
  }
</script>

<article class="query-variant variant-c">
  <header class="workbench-header">
    <div><span class="eyebrow">Ground Ball workbench</span><strong>{previewState === 'results' ? '6 player-seasons' : 'Power + speed'}</strong></div>
    <span class="source-light">● Verified</span>
  </header>

  <div class="workbench-question">
    <textarea aria-label="Example baseball question" bind:value={question} rows="2"></textarea>
    <div class="recipe-summary">
      {#each RECIPE as part}<span>{part.value}</span>{/each}
    </div>
  </div>

  <nav class="workbench-tabs" aria-label="Prototype workbench views">
    <button type="button" class:active={view === 'build'} on:click={() => (view = 'build')}>Build</button>
    <button type="button" class:active={view === 'results'} on:click={() => (view = 'results')}>Results <span>6</span></button>
    <button type="button" class:active={view === 'verify'} on:click={() => (view = 'verify')}>Verify</button>
  </nav>

  {#if view === 'build'}
    <section class="workbench-view build-view">
      {#if previewState === 'clarify'}
        <div class="workbench-clarification">
          <span>Resolve one field</span><strong>{CLARIFICATION_QUESTION}</strong>
          <p>Choose the source column Ground Ball should use.</p>
          <button type="button" on:click={() => setPreviewState('results')}>Pitching · SO</button>
          <button type="button" on:click={() => setPreviewState('results')}>Batting · SO</button>
        </div>
      {:else}
        <div class="clause-editor">
          {#each RECIPE as part, index}
            <button type="button"><small>{index + 1} · {part.label}</small><strong>{part.value}</strong><span>›</span></button>
          {/each}
          <button class="add-clause" type="button">+ Add clause</button>
        </div>
        <div class="field-shelf">
          <div><strong>Field shelf</strong><button type="button">Search all fields</button></div>
          {#each FIELD_GROUPS as group}
            <section><small>{group.name}</small><p>{group.fields.join(' · ')}</p></section>
          {/each}
        </div>
        <button class="primary-prototype-action" type="button" on:click={() => setPreviewState('results')}>Run this recipe →</button>
      {/if}
    </section>
  {:else if view === 'results'}
    <section class="workbench-view results-view">
      <div class="result-hero"><span>Matched</span><strong>6</strong><p>player-seasons in the Lahman batting record</p></div>
      <div class="player-card-rail">
        {#each RESULTS as row}
          <article><span>{row.year}</span><strong>{row.player}</strong><div><b>{row.hr}</b> HR <b>{row.sb}</b> SB</div></article>
        {/each}
      </div>
      <div class="result-controls"><button type="button">+ Field</button><button type="button">Sort: Season</button><button type="button" on:click={() => (view = 'verify')}>Evidence →</button></div>
    </section>
  {:else}
    <section class="workbench-view verify-view">
      <div class="verification-status"><span>✓</span><div><strong>Verified from Lahman</strong><p>Batting · Version 2025 · 6 source rows</p></div></div>
      <details open><summary>Query recipe</summary><p>Players · same season · HR ≥ 40 · SB ≥ 40</p></details>
      <details><summary>Generated SQL</summary><code>HAVING SUM(HR) &gt;= 40 AND SUM(SB) &gt;= 40</code></details>
      <div class="verify-actions"><button type="button">Download CSV</button><button type="button">Download JSON</button></div>
    </section>
  {/if}
</article>

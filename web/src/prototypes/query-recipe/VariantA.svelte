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

  let question = EXAMPLE_QUESTION;
  let fieldsOpen = false;
</script>

<article class="query-variant variant-a">
  <header class="prototype-page-heading">
    <span class="eyebrow">Explore the record</span>
    <h2>Ask naturally. Refine precisely.</h2>
    <p>Ground Ball shows its work before it runs the query.</p>
  </header>

  {#if previewState === 'clarify'}
    <section class="prototype-card clarification-card">
      <span class="prototype-label">One detail needed</span>
      <p class="clarification-question">{CLARIFICATION_QUESTION}</p>
      <div class="recipe-line">
        <button type="button" class="recipe-token">Players</button>
        <button type="button" class="recipe-token unresolved">Strikeouts ?</button>
        <button type="button" class="recipe-token">2024</button>
      </div>
      <p class="clarification-copy">Which kind of strikeouts should Ground Ball rank?</p>
      <div class="clarification-actions">
        <button type="button" on:click={() => setPreviewState('results')}>Pitching strikeouts</button>
        <button type="button" on:click={() => setPreviewState('results')}>Batting strikeouts</button>
      </div>
      <button class="text-action" type="button" on:click={() => setPreviewState('example')}>Edit the question</button>
    </section>
  {:else}
    <section class="prototype-card example-card">
      <div class="prototype-card-heading">
        <div><span class="prototype-label">Editable example</span><strong>Power + speed</strong></div>
        <span class="verified-pill">Verified data</span>
      </div>
      <label for="variant-a-question">Baseball question</label>
      <textarea id="variant-a-question" bind:value={question} rows="3"></textarea>

      <div class="understood-heading">
        <span>Ground Ball understood</span><button type="button">Edit all</button>
      </div>
      <div class="recipe-line" aria-label="Interpreted query recipe">
        {#each RECIPE as part}
          <button type="button" class="recipe-token"><small>{part.label}</small>{part.value}</button>
        {/each}
        <button type="button" class="recipe-token add-token" on:click={() => (fieldsOpen = !fieldsOpen)}>+ Field or filter</button>
      </div>

      {#if fieldsOpen}
        <div class="field-picker">
          <div class="field-search">⌕ Search every Lahman field</div>
          {#each FIELD_GROUPS as group}
            <div><strong>{group.name}</strong><span>{group.fields.join(' · ')}</span></div>
          {/each}
        </div>
      {/if}

      <button class="primary-prototype-action" type="button" on:click={() => setPreviewState('results')}>Run example <span>→</span></button>
    </section>

    {#if previewState === 'results'}
      <section class="prototype-card result-stack">
        <div class="prototype-card-heading">
          <div><span class="prototype-label">6 player-seasons</span><strong>The 40–40 club</strong></div>
          <button type="button" class="small-control">Sort: Season</button>
        </div>
        <div class="compact-result-list">
          {#each RESULTS as row}
            <div class="compact-result-row">
              <div><strong>{row.player}</strong><span>{row.year}</span></div>
              <div><b>{row.hr}</b> HR <b>{row.sb}</b> SB</div>
            </div>
          {/each}
        </div>
      </section>
    {/if}
  {/if}

  <details class="prototype-tools" open={previewState === 'results'}>
    <summary>More tools <span>Fields · Evidence · Export</span></summary>
    <div class="tool-grid">
      <button type="button" on:click={() => (fieldsOpen = !fieldsOpen)}>Browse fields</button>
      <button type="button">Lahman Batting ✓</button>
      <button type="button">View SQL</button>
      <button type="button">CSV</button>
      <button type="button">JSON</button>
    </div>
  </details>
</article>

<script>
  import {
    CLARIFICATION_QUESTION,
    EXAMPLE_QUESTION,
    FIELD_GROUPS,
    RESULTS,
  } from './fixtures.js';

  export let previewState = 'example';
  export let setPreviewState = () => {};

  let question = EXAMPLE_QUESTION;
  let drawer = 'none';
</script>

<article class="query-variant variant-b">
  <header class="b-command-header">
    <span class="eyebrow">Query scorecard</span>
    <h2>Build the baseball question</h2>
    <textarea aria-label="Example baseball question" bind:value={question} rows="2"></textarea>
  </header>

  <section class="scorecard-steps" aria-label="Query recipe steps">
    <div class="score-step">
      <span class="step-number">1</span>
      <div><small>Who</small><strong>Players</strong><p>Search the complete player record.</p></div>
      <button type="button">Edit</button>
    </div>
    <div class="score-step">
      <span class="step-number">2</span>
      <div><small>Grain</small><strong>Same season</strong><p>Combine team stints before comparing.</p></div>
      <button type="button">Edit</button>
    </div>

    {#if previewState === 'clarify'}
      <div class="score-step clarification-step">
        <span class="step-number">3</span>
        <div class="step-wide">
          <small>Choose a meaning</small><strong>{CLARIFICATION_QUESTION}</strong>
          <p>“Strikeouts” appears in both batting and pitching records.</p>
          <div class="choice-tiles">
            <button type="button" on:click={() => setPreviewState('results')}><b>Pitching SO</b><span>Strikeouts recorded</span></button>
            <button type="button" on:click={() => setPreviewState('results')}><b>Batting SO</b><span>Times struck out</span></button>
          </div>
        </div>
      </div>
    {:else}
      <div class="score-step conditions-step">
        <span class="step-number">3</span>
        <div class="step-wide">
          <small>Conditions</small>
          <div class="stat-scorecards">
            <button type="button"><span>HR</span><strong>40+</strong><small>Home runs</small></button>
            <span class="plus-mark">+</span>
            <button type="button"><span>SB</span><strong>40+</strong><small>Stolen bases</small></button>
          </div>
        </div>
      </div>
    {/if}

    <div class="score-step">
      <span class="step-number">4</span>
      <div><small>Show</small><strong>Player · Season · HR · SB</strong><p>Four columns, sorted by season.</p></div>
      <button type="button" on:click={() => (drawer = 'fields')}>Fields</button>
    </div>
  </section>

  {#if previewState === 'results'}
    <section class="scoreboard-results">
      <div class="scoreboard-heading"><span>Result</span><strong>6 qualifying seasons</strong></div>
      {#each RESULTS as row, index}
        <div class="scoreboard-row">
          <span class="rank">{index + 1}</span>
          <div><strong>{row.player}</strong><small>{row.year}</small></div>
          <div class="score-values"><span>{row.hr}<small>HR</small></span><span>{row.sb}<small>SB</small></span></div>
        </div>
      {/each}
    </section>
  {/if}

  {#if drawer === 'fields'}
    <section class="b-drawer">
      <div class="prototype-card-heading"><strong>Add a field</strong><button type="button" on:click={() => (drawer = 'none')}>Close</button></div>
      {#each FIELD_GROUPS as group}
        <div><small>{group.name}</small>{#each group.fields as field}<button type="button">+ {field}</button>{/each}</div>
      {/each}
    </section>
  {/if}

  <footer class="b-action-dock">
    <button type="button" on:click={() => (drawer = 'fields')}>Fields</button>
    <button type="button" on:click={() => (drawer = 'evidence')}>Evidence ✓</button>
    <button type="button" on:click={() => (drawer = 'export')}>Export</button>
    <button class="run-scorecard" type="button" on:click={() => setPreviewState('results')}>Run →</button>
  </footer>

  {#if drawer === 'evidence' || drawer === 'export'}
    <section class="b-inline-note">
      {drawer === 'evidence' ? 'Lahman Batting · Version 2025 · SQL available' : 'Download this result as CSV or JSON'}
    </section>
  {/if}
</article>

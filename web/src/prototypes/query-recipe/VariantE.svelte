<script>
  import ChatComposer from './ChatComposer.svelte';
  import DetailsSheet from './DetailsSheet.svelte';
  import { CLARIFICATION_QUESTION, EXAMPLE_QUESTION, RESULTS } from './fixtures.js';

  export let previewState = 'answer';
  export let setPreviewState = () => {};

  let draft = previewState === 'start' ? EXAMPLE_QUESTION : '';
  let priorPreviewState = previewState;
  $: if (previewState !== priorPreviewState) {
    draft = previewState === 'start' ? EXAMPLE_QUESTION : '';
    priorPreviewState = previewState;
  }

  function submit() {
    setPreviewState('answer');
    draft = '';
  }
</script>

<article class="chat-variant search-variant">
  <header class="search-header"><strong>Ground Ball</strong><button type="button" aria-label="Question history">History</button></header>

  {#if previewState === 'start'}
    <section class="search-welcome">
      <small>BASEBALL, ANSWERED</small>
      <h1>What do you want to know?</h1>
      <p>The 40–40 example is ready in the question box below.</p>
    </section>
  {:else if previewState === 'clarify'}
    <section class="search-answer clarification-page">
      <small>ONE DETAIL NEEDED</small>
      <h1>{CLARIFICATION_QUESTION}</h1>
      <p>Should Ground Ball use the pitching or batting field?</p>
      <button type="button" on:click={() => setPreviewState('answer')}>Pitching strikeouts</button>
      <button type="button" on:click={() => setPreviewState('answer')}>Batting strikeouts</button>
    </section>
  {:else}
    <section class="search-answer">
      <p class="active-question">{EXAMPLE_QUESTION}</p>
      <div class="answer-title"><div><small>ANSWER</small><h1>The 40–40 club has six qualifying seasons.</h1></div><button type="button" on:click={() => setPreviewState('details')}>Details</button></div>
      <div class="result-table" role="table" aria-label="40-40 player seasons">
        <div class="table-head" role="row"><span>Player</span><span>Season</span><span>HR</span><span>SB</span></div>
        {#each RESULTS as row}
          <div role="row"><strong>{row.player}</strong><span>{row.year}</span><b>{row.hr}</b><b>{row.sb}</b></div>
        {/each}
      </div>
    </section>
  {/if}

  <div class="chat-dock"><ChatComposer bind:value={draft} onSubmit={submit} placeholder="Ask or refine…" /></div>
  {#if previewState === 'details'}<DetailsSheet onClose={() => setPreviewState('answer')} />{/if}
</article>

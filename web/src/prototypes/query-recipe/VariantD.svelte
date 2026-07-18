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

<article class="chat-variant conversation-variant">
  <header class="chat-header"><strong>Ground Ball</strong><button type="button" aria-label="Start new question">＋</button></header>

  {#if previewState === 'start'}
    <section class="chat-welcome">
      <span class="gb-mark">GB</span>
      <h1>Ask Ground Ball</h1>
      <p>Baseball answers from the record, with the details there when you want them.</p>
      <small>EDITABLE EXAMPLE</small>
    </section>
  {:else if previewState === 'clarify'}
    <section class="conversation-thread">
      <p class="user-message">{CLARIFICATION_QUESTION}</p>
      <div class="assistant-answer clarification-answer">
        <h1>Which kind of strikeouts?</h1>
        <p>That statistic appears in both batting and pitching records.</p>
        <button type="button" on:click={() => setPreviewState('answer')}>Pitching strikeouts</button>
        <button type="button" on:click={() => setPreviewState('answer')}>Batting strikeouts</button>
      </div>
    </section>
  {:else}
    <section class="conversation-thread">
      <p class="user-message">{EXAMPLE_QUESTION}</p>
      <div class="assistant-answer">
        <h1>Six player-seasons match.</h1>
        <div class="answer-explainer">
          <p>These are the complete 40–40 seasons in the loaded record.</p>
          <button type="button" on:click={() => setPreviewState('details')}>Details</button>
        </div>
        <div class="plain-result-list">
          {#each RESULTS as row}
            <div><span><strong>{row.player}</strong><small>{row.year}</small></span><span><b>{row.hr}</b> HR&nbsp;&nbsp;<b>{row.sb}</b> SB</span></div>
          {/each}
        </div>
      </div>
    </section>
  {/if}

  <div class="chat-dock"><ChatComposer bind:value={draft} onSubmit={submit} /></div>
  {#if previewState === 'details'}<DetailsSheet onClose={() => setPreviewState('answer')} />{/if}
</article>

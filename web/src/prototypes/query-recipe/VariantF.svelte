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

<article class="chat-variant feed-variant">
  <div class="feed-context">Historical MLB</div>

  {#if previewState === 'start'}
    <section class="feed-welcome"><h1>Ask the record.</h1><p>Edit the example in the chat box and send it when you’re ready.</p></section>
  {:else if previewState === 'clarify'}
    <section class="feed-clarification">
      <small>{CLARIFICATION_QUESTION}</small><h1>Batting or pitching strikeouts?</h1>
      <div><button type="button" on:click={() => setPreviewState('answer')}>Pitching</button><button type="button" on:click={() => setPreviewState('answer')}>Batting</button></div>
    </section>
  {:else}
    <section class="feed-answer">
      <p class="feed-question">{EXAMPLE_QUESTION}</p>
      <h1>Six players reached 40 HR and 40 SB in one season.</h1>
      <div class="season-feed">
        {#each RESULTS as row}
          <button type="button"><time>{row.year}</time><strong>{row.player}</strong><span><b>{row.hr}</b> HR · <b>{row.sb}</b> SB</span></button>
        {/each}
      </div>
      <button class="feed-source" type="button" on:click={() => setPreviewState('details')}>Details ›</button>
    </section>
  {/if}

  <div class="chat-dock">
    <ChatComposer bind:value={draft} onSubmit={submit} />
  </div>
  {#if previewState === 'details'}<DetailsSheet onClose={() => setPreviewState('answer')} />{/if}
</article>

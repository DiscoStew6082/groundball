<script>
  import { tick } from 'svelte';

  import ChatComposer from './ChatComposer.svelte';
  import DetailsSheet from './DetailsSheet.svelte';
  import SettingsMenu from './SettingsMenu.svelte';
  import { CLARIFICATION_QUESTION, EXAMPLE_QUESTION, RESULTS } from './fixtures.js';

  export let previewState = 'answer';
  export let setPreviewState = () => {};

  let draft = previewState === 'start' ? EXAMPLE_QUESTION : '';
  let priorPreviewState = previewState;
  let settingsOpen = new URLSearchParams(window.location.search).get('menu') === '1';
  let selectedSection = 'Query';
  let composer;
  $: if (previewState !== priorPreviewState) {
    draft = previewState === 'start' ? EXAMPLE_QUESTION : '';
    priorPreviewState = previewState;
  }

  function submit() {
    setPreviewState('answer');
    draft = '';
    settingsOpen = false;
  }

  function toggleSettings() {
    settingsOpen = !settingsOpen;
  }

  async function closeSettings() {
    settingsOpen = false;
    await tick();
    composer?.focusSettings();
  }

  function chooseSection(section) {
    selectedSection = section;
    closeSettings();
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

  {#if settingsOpen}
    <button class="settings-popover-backdrop" type="button" tabindex="-1" aria-label="Close sections and settings" on:click={closeSettings}></button>
    <SettingsMenu selected={selectedSection} onSelect={chooseSection} onClose={closeSettings} />
  {/if}
  <div class="chat-dock">
    <ChatComposer
      bind:this={composer}
      bind:value={draft}
      onSubmit={submit}
      showSettings={true}
      {settingsOpen}
      onToggleSettings={toggleSettings}
    />
  </div>
  {#if previewState === 'details'}<DetailsSheet onClose={() => setPreviewState('answer')} />{/if}
</article>

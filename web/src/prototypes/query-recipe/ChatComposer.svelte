<script>
  export let value = '';
  export let placeholder = 'Ask a baseball question…';
  export let onSubmit = () => {};
  export let showSettings = false;
  export let settingsOpen = false;
  export let onToggleSettings = () => {};

  let settingsButton;

  export function focusSettings() {
    settingsButton?.focus({ preventScroll: true });
  }

  function submit() {
    const question = value.trim();
    if (question) onSubmit(question);
  }

  function handleKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }
</script>

<form class:with-settings={showSettings} class="chat-composer" on:submit|preventDefault={submit}>
  {#if showSettings}
    <button
      bind:this={settingsButton}
      class="composer-settings"
      type="button"
      aria-label="Open sections and settings"
      aria-expanded={settingsOpen}
      aria-controls="app-sections-menu"
      on:click={onToggleSettings}
    >⚙</button>
  {/if}
  <textarea bind:value rows="1" aria-label="Ask Ground Ball" {placeholder} on:keydown={handleKeydown}></textarea>
  <button class="composer-send" type="submit" aria-label="Send question">↑</button>
</form>

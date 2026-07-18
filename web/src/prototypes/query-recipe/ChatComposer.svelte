<script>
  export let value = '';
  export let placeholder = 'Ask a baseball question…';
  export let onSubmit = () => {};

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

<form class="chat-composer" on:submit|preventDefault={submit}>
  <textarea bind:value rows="1" aria-label="Ask Ground Ball" {placeholder} on:keydown={handleKeydown}></textarea>
  <button class="composer-send" type="submit" aria-label="Send question">↑</button>
</form>

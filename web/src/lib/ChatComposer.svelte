<script>
  export let value = '';
  export let pending = false;
  export let onSubmit = () => {};

  function submit() {
    const question = value.trim();
    if (question && !pending) onSubmit(question);
  }

  function handleKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }
</script>

<form class="chat-composer" on:submit|preventDefault={submit}>
  <textarea
    bind:value
    rows="1"
    aria-label="Ask Ground Ball"
    placeholder="Ask a baseball question…"
    disabled={pending}
    on:keydown={handleKeydown}
  ></textarea>
  <button type="submit" aria-label="Send question" disabled={pending || !value.trim()}>
    {pending ? '…' : '↑'}
  </button>
</form>

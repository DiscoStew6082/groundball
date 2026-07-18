<script>
  import { onDestroy, onMount } from 'svelte';

  export let onClose = () => {};

  let sheet;
  let closeButton;
  let previousFocus;

  onMount(() => {
    previousFocus = document.activeElement;
    closeButton?.focus();
  });

  onDestroy(() => {
    previousFocus?.focus?.();
  });

  function handleKeydown(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;

    const focusable = [...sheet.querySelectorAll('button, summary, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
      .filter((element) => !element.disabled);
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<div class="details-backdrop" aria-hidden="true"></div>
<div class="details-sheet" role="dialog" aria-modal="true" aria-labelledby="answer-details-title" bind:this={sheet}>
  <header>
    <div><small>ANSWER DETAILS</small><h2 id="answer-details-title">How Ground Ball answered</h2></div>
    <button bind:this={closeButton} type="button" aria-label="Close details" on:click={onClose}>×</button>
  </header>

  <section>
    <small>UNDERSTOOD AS</small>
    <p>Player seasons · regular season · all years · HR ≥ 40 · SB ≥ 40</p>
  </section>
  <section>
    <small>DATA USED</small>
    <p>Lahman Batting and People tables · 6 matching source rows</p>
  </section>
  <section>
    <small>FIELDS</small>
    <p>Player · Season · Home runs · Stolen bases</p>
  </section>

  <div class="details-actions">
    <button type="button">Export CSV</button>
    <button type="button">View source rows</button>
  </div>
  <details>
    <summary>Generated SQL</summary>
    <code>HAVING SUM(HR) &gt;= 40 AND SUM(SB) &gt;= 40</code>
  </details>
</div>

<script>
  import { onDestroy, onMount } from 'svelte';

  export let result;
  export let recipeText = '';
  export let pending = false;
  export let onClose = () => {};
  export let onRunRecipe = () => {};
  export let onExport = () => {};
  export let onBrowseFields = () => {};

  let sheet;
  let closeButton;
  let previousFocus;
  let draft = recipeText;
  let priorRecipeText = recipeText;

  $: if (recipeText !== priorRecipeText) {
    draft = recipeText;
    priorRecipeText = recipeText;
  }

  onMount(() => {
    previousFocus = document.activeElement;
    closeButton?.focus({ preventScroll: true });
  });

  onDestroy(() => previousFocus?.focus?.({ preventScroll: true }));

  function handleKeydown(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = [...sheet.querySelectorAll('button, summary, a[href], textarea, [tabindex]:not([tabindex="-1"])')]
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

<button class="sheet-backdrop" type="button" aria-label="Close details backdrop" on:click={onClose}></button>
<div class="details-sheet" role="dialog" aria-modal="true" aria-labelledby="details-title" bind:this={sheet}>
  <header>
    <div><small>QUERY DETAILS</small><h2 id="details-title">How Ground Ball answered</h2></div>
    <button bind:this={closeButton} type="button" aria-label="Close details" on:click={onClose}>×</button>
  </header>

  <section>
    <h3>Query Recipe</h3>
    <textarea bind:value={draft} aria-label="Structured Query Recipe" rows="11"></textarea>
    <button class="secondary-action" type="button" disabled={pending} on:click={() => onRunRecipe(draft)}>Run edited recipe</button>
    <button class="secondary-action" type="button" on:click={onBrowseFields}>Browse fields</button>
  </section>

  <details open>
    <summary>Query Plan</summary>
    <pre>{JSON.stringify(result.plan, null, 2)}</pre>
  </details>

  {#if result.evidence?.calculations?.length}
    <section>
      <h3>Calculations</h3>
      {#each result.evidence.calculations as calculation}
        <p><strong>{calculation.identity}</strong> = {calculation.formula}</p>
        <small>Inputs: {calculation.inputs.join(', ')}</small>
      {/each}
    </section>
  {/if}

  {#if result.rows}
    <details>
      <summary>Rows ({result.rows.length})</summary>
      <pre>{JSON.stringify(result.rows, null, 2)}</pre>
    </details>
  {/if}

  {#if result.evidence}
    <details open>
      <summary>Evidence</summary>
      <dl>
        <dt>Catalog</dt><dd>{result.evidence.catalog_revision}</dd>
        <dt>Data release</dt><dd>{result.evidence.data_release}</dd>
        <dt>Matched rows</dt><dd>{result.evidence.matched_row_count}</dd>
        <dt>Fingerprint</dt><dd>{result.evidence.result_fingerprint}</dd>
      </dl>
      <h3>Parameterized SQL</h3>
      <pre>{result.evidence.parameterized_sql}</pre>
      <h3>Bound values</h3>
      <pre>{JSON.stringify(result.evidence.bound_values, null, 2)}</pre>
      <h3>Sources</h3>
      <pre>{JSON.stringify(result.evidence.sources, null, 2)}</pre>
    </details>
  {/if}

  <section class="verification-state">
    <h3>{result.verification?.status === 'verified' ? 'Verified for this data release' : 'Verification unavailable'}</h3>
    <p>{result.verification?.reason ?? 'Coverage proof is not available.'}</p>
    {#if result.verification?.coverage_report}
      <a href={result.verification.coverage_report}>Open Coverage Report</a>
    {:else}
      <button type="button" disabled>Coverage Report unavailable</button>
    {/if}
  </section>

  {#if result.rows}
    <div class="details-actions">
      <button type="button" disabled={pending} on:click={() => onExport('csv')}>Export CSV</button>
      <button type="button" disabled={pending} on:click={() => onExport('json')}>Export JSON</button>
    </div>
  {/if}
</div>

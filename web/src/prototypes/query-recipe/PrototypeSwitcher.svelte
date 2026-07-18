<script>
  export let variants = [];
  export let current = 'A';
  export let onPrevious = () => {};
  export let onNext = () => {};

  $: currentVariant = variants.find((variant) => variant.key === current) ?? variants[0];
</script>

{#if import.meta.env.DEV}
  <nav class="prototype-switcher" aria-label="Prototype variant switcher">
    <button type="button" aria-label="Previous prototype variant" on:click={onPrevious}>←</button>
    <span><strong>{currentVariant?.key}</strong> — {currentVariant?.name}</span>
    <button type="button" aria-label="Next prototype variant" on:click={onNext}>→</button>
  </nav>
{/if}

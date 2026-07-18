<script>
  import VariantA from './VariantA.svelte';
  import VariantB from './VariantB.svelte';
  import VariantC from './VariantC.svelte';
  import PrototypeSwitcher from './PrototypeSwitcher.svelte';
  import './prototype.css';

  // Three mobile Query Recipe variants, switchable via ?variant=, on the existing app route.
  const variants = [
    { key: 'A', name: 'Recipe stack' },
    { key: 'B', name: 'Guided scorecard' },
    { key: 'C', name: 'Three-view workbench' },
  ];
  const states = [
    { key: 'example', label: 'Example' },
    { key: 'results', label: 'Results' },
    { key: 'clarify', label: 'Clarification' },
  ];

  let variant = readChoice('variant', variants.map((item) => item.key), 'A');
  let previewState = readChoice('state', states.map((item) => item.key), 'example');

  function readChoice(key, allowed, fallback) {
    const value = new URLSearchParams(window.location.search).get(key);
    return allowed.includes(value) ? value : fallback;
  }

  function writeChoice(key, value) {
    const url = new URL(window.location.href);
    url.searchParams.set(key, value);
    window.history.replaceState({}, '', url);
  }

  function setVariant(nextVariant) {
    variant = nextVariant;
    writeChoice('variant', variant);
  }

  function setPreviewState(nextState) {
    previewState = nextState;
    writeChoice('state', previewState);
  }

  function cycleVariant(direction) {
    const index = variants.findIndex((item) => item.key === variant);
    const nextIndex = (index + direction + variants.length) % variants.length;
    setVariant(variants[nextIndex].key);
  }

  function handleKeydown(event) {
    const tag = event.target?.tagName?.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || event.target?.isContentEditable) return;
    if (event.key === 'ArrowLeft') cycleVariant(-1);
    if (event.key === 'ArrowRight') cycleVariant(1);
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<section class="prototype-host" aria-label="Mobile Query Recipe prototype">
  <aside class="prototype-evaluator" aria-label="Prototype preview state">
    <span>Prototype state</span>
    <div>
      {#each states as state}
        <button
          type="button"
          class:active={previewState === state.key}
          on:click={() => setPreviewState(state.key)}
        >{state.label}</button>
      {/each}
    </div>
  </aside>

  <div class="prototype-phone">
    {#if variant === 'A'}
      <VariantA {previewState} {setPreviewState} />
    {:else if variant === 'B'}
      <VariantB {previewState} {setPreviewState} />
    {:else}
      <VariantC {previewState} {setPreviewState} />
    {/if}
  </div>

  <PrototypeSwitcher
    {variants}
    current={variant}
    onPrevious={() => cycleVariant(-1)}
    onNext={() => cycleVariant(1)}
  />
</section>

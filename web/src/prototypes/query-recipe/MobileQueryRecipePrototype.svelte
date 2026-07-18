<script>
  import VariantD from './VariantD.svelte';
  import VariantE from './VariantE.svelte';
  import VariantF from './VariantF.svelte';
  import PrototypeSwitcher from './PrototypeSwitcher.svelte';
  import SettingsMenu from './SettingsMenu.svelte';
  import './chat-prototype.css';

  export let settingsOpen = false;
  export let onCloseSettings = () => {};

  // Three answer-first chat variants, switchable via ?variant=, on the existing app route.
  const variants = [
    { key: 'D', name: 'Rich chat answer' },
    { key: 'E', name: 'Search answer page' },
    { key: 'F', name: 'Sports feed answer' },
  ];
  const states = [
    { key: 'start', label: 'Start' },
    { key: 'answer', label: 'Answer' },
    { key: 'clarify', label: 'Clarify' },
    { key: 'details', label: 'Details' },
  ];

  const presentationMode = new URLSearchParams(window.location.search).get('presentation') === '1';
  let variant = readChoice('variant', variants.map((item) => item.key), 'D');
  let previewState = readChoice('state', states.map((item) => item.key), 'answer');
  let selectedSection = 'Query';

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

  function chooseSection(section) {
    selectedSection = section;
    onCloseSettings();
  }

  function handleKeydown(event) {
    const tag = event.target?.tagName?.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || event.target?.isContentEditable) return;
    if (event.key === 'ArrowLeft') cycleVariant(-1);
    if (event.key === 'ArrowRight') cycleVariant(1);
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<section class="prototype-host" aria-label="Answer-first mobile chat prototype">
  {#if settingsOpen}
    <button
      class="settings-popover-backdrop"
      type="button"
      tabindex="-1"
      aria-label="Close application sections"
      on:click={onCloseSettings}
    ></button>
    <SettingsMenu selected={selectedSection} onSelect={chooseSection} onClose={onCloseSettings} />
  {/if}

  {#if !presentationMode}
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
  {/if}

  <div class="prototype-phone">
    {#if variant === 'D'}
      <VariantD {previewState} {setPreviewState} />
    {:else if variant === 'E'}
      <VariantE {previewState} {setPreviewState} />
    {:else}
      <VariantF {previewState} {setPreviewState} />
    {/if}
  </div>

  {#if !presentationMode}
    <PrototypeSwitcher
      {variants}
      current={variant}
      onPrevious={() => cycleVariant(-1)}
      onNext={() => cycleVariant(1)}
    />
  {/if}
</section>

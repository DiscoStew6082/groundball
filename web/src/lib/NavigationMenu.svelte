<script>
  import { onMount } from 'svelte';

  export let active = 'Query';
  export let onSelect = () => {};
  export let onClose = () => {};

  const sections = [
    ['Query', 'Ask the record'],
    ['Evidence', 'Last Query Run details'],
    ['Browse fields', 'Raw and promoted catalog'],
    ['History', 'Recipe and run snapshots'],
    ['Architecture', 'How the query path works'],
  ];
  let sectionButtons = [];

  onMount(() => sectionButtons[0]?.focus({ preventScroll: true }));

  function handleKeydown(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
    }
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<button class="menu-backdrop" type="button" aria-label="Close application navigation" on:click={onClose}></button>
<div class="navigation-menu" role="menu" aria-label="Application navigation">
  <small>GROUND BALL</small>
  {#each sections as section, index}
    <button
      bind:this={sectionButtons[index]}
      type="button"
      role="menuitem"
      class:active={active === section[0]}
      on:click={() => onSelect(section[0])}
    >
      <strong>{section[0]}</strong>
      <span>{section[1]}</span>
    </button>
  {/each}
</div>

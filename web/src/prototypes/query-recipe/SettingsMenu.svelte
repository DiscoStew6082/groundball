<script>
  import { onMount } from 'svelte';

  export let selected = 'Query';
  export let onSelect = () => {};
  export let onClose = () => {};

  const sections = [
    { name: 'Query', description: 'Ask the record' },
    { name: 'Evidence', description: 'Sources and answer details' },
    { name: 'History', description: 'Recent questions' },
    { name: 'Architecture', description: 'How Ground Ball works' },
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

<nav class="settings-popover" id="app-sections-menu" aria-label="Application sections">
  <small>GROUND BALL</small>
  {#each sections as section, index}
    <button
      bind:this={sectionButtons[index]}
      type="button"
      class:active={selected === section.name}
      aria-current={selected === section.name ? 'page' : undefined}
      on:click={() => onSelect(section.name)}
    >
      <span>{section.name}</span><small>{section.description}</small>
    </button>
  {/each}
</nav>

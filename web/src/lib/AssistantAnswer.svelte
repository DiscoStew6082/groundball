<script>
  export let answer;

  function fixtureTime(value) {
    if (typeof value !== 'string' || !value.trim()) return 'Time unavailable';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
    }).format(date);
  }

  function downloadAnswer() {
    const blob = new Blob([JSON.stringify(answer, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'ground-ball-answer.json';
    link.click();
    URL.revokeObjectURL(url);
  }

  function httpsUrl(value) {
    if (typeof value !== 'string') return null;
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && !url.username && !url.password ? url.href : null;
    } catch {
      return null;
    }
  }

  $: sources = Array.isArray(answer.sources) ? answer.sources : [];
  $: credits = [
    ...(Array.isArray(answer.attributions) ? answer.attributions : []),
    ...sources.filter((source) => source.attribution).map((source) => ({
      provider: source.title, text: source.attribution, url: source.url,
    })),
  ].filter((credit, index, all) => credit.text && all.findIndex((other) => other.text === credit.text) === index);
</script>

<div class="assistant-answer">
  <small>SOURCED ANSWER</small>
  <h2>{answer.title}</h2>
  {#if answer.summary}<p>{answer.summary}</p>{/if}

  {#if answer.fixture}
    <section class="fixture" aria-label="Game details">
      <h3>{answer.fixture.away_team} at {answer.fixture.home_team}</h3>
      <p><time datetime={answer.fixture.starts_at}>{fixtureTime(answer.fixture.starts_at)}</time></p>
      <p>{answer.fixture.venue} · {answer.fixture.status === 'NS' ? 'Scheduled' : answer.fixture.status}</p>
    </section>
  {/if}

  <ol class="facts" aria-label="Sourced facts">
    {#each answer.facts ?? [] as fact}
      <li>
        <p>{fact.text}
          {#each fact.source_ids ?? [] as sourceId}
            {@const source = sources.find((item) => item.id === sourceId)}
            {#if source}
              {@const href = httpsUrl(source.url)}
              {#if href}<a class="citation" {href} target="_blank" rel="noopener noreferrer">[{source.title}]</a>
              {:else}<span class="citation">[{source.title}]</span>{/if}
            {/if}
          {/each}
        </p>
        {#if fact.query_run}
          <details aria-label="Historical query evidence"><summary>Historical query evidence</summary><pre>{JSON.stringify(fact.query_run, null, 2)}</pre></details>
        {/if}
      </li>
    {/each}
  </ol>

  {#if answer.limitations?.length}
    <section aria-label="Answer limitations"><h3>Scope and limits</h3><ul>{#each answer.limitations as limitation}<li>{limitation}</li>{/each}</ul></section>
  {/if}

  {#if credits.length}
    <section class="source-credit" aria-label="Source attribution">
      <h3>Source attribution</h3>
      {#each credits as credit}
        {@const href = httpsUrl(credit.url)}
        <p>{credit.text}
          {#if href}<a {href} target="_blank" rel="noopener noreferrer">{credit.provider}</a>{/if}
        </p>
      {/each}
    </section>
  {/if}

  <details aria-label="Source evidence">
    <summary>Source evidence and observation times</summary>
    {#each sources as source}
      <section class="source-record">
        <h3>{source.title}</h3>
        <dl>
          <dt>Observed</dt><dd><time datetime={source.observed_at}>{source.observed_at}</time></dd>
          <dt>License</dt><dd>{source.license}</dd>
          <dt>Fingerprint</dt><dd>{source.fingerprint}</dd>
        </dl>
        <pre>{JSON.stringify(source.record, null, 2)}</pre>
      </section>
    {/each}
  </details>
  <button type="button" on:click={downloadAnswer}>Download answer JSON</button>
</div>

<style>
  .assistant-answer { min-width: 0; overflow-wrap: anywhere; font-size: 14px; line-height: 1.6; }
  small { color: var(--accent); font-size: 10px; letter-spacing: .1em; }
  h2 { margin: 0; font: 500 clamp(25px, 5vw, 34px)/1.2 Georgia, serif; }
  h3 { margin: 0 0 8px; font-size: 14px; }
  p { margin: 10px 0; }
  a { color: #e4c773; text-underline-offset: 3px; }
  .citation { display: inline-block; padding: 5px 3px; font-size: 12px; }
  .facts, ul { padding-left: 22px; }
  .facts > li { margin: 16px 0; }
  section, details { margin-top: 18px; }
  .fixture, .source-credit, details { padding: 14px; border: 1px solid var(--line-strong); border-radius: 10px; background: var(--panel); }
  .source-credit { border-color: #756232; }
  .source-credit p { font-size: 13px; }
  summary { min-height: 44px; align-content: center; }
  button { min-height: 48px; margin-top: 16px; padding: 0 14px; border: 1px solid var(--line-strong); border-radius: 9px; color: var(--text); background: var(--panel-raised); }
  dl { display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: 8px; font-size: 12px; }
  dt { color: var(--muted); }
  dd { margin: 0; min-width: 0; }
  pre { max-width: 100%; max-height: 320px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; padding: 12px; border: 1px solid var(--line); border-radius: 8px; color: #c8dfd0; background: var(--bg); font: 12px/1.6 monospace; }
</style>

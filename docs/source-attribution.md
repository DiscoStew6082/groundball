# Source attribution

Ground Ball keeps application licensing separate from source-data terms. `src/baseball_rag/source_attribution.py` owns the credits attached to responses. Source records retain their URLs, license labels, evidence, and fingerprints; answer JSON downloads preserve these fields.

## Retrosheet

The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".

[Retrosheet](https://www.retrosheet.org/) provides historical records used by supported event queries and World Series context. Its required credit is shown visibly when those records are included. The tracked legal record is [`release/legal/retrosheet.json`](../release/legal/retrosheet.json); immutable Release Bundles carry their corresponding legal record. Retrosheet may correct its records, and Ground Ball retains provenance for the specific evidence used.

## Other sources

- Historical statistics: Sean Lahman / SABR, via NeuML, with CC BY-SA 3.0 metadata retained in [`release/legal/lahman-neuml.json`](../release/legal/lahman-neuml.json) and the data manifest.
- Fixture metadata: TheSportsDB, with its source attribution and API terms recorded in the answer. A listed fixture does not establish schedule completeness.
- Stat definitions: concise reviewed project text linked to individual MLB glossary pages through corpus `source_url` metadata. The citation identifies the reference; it does not imply that the full glossary text is distributed here.

The project license does not replace these source terms. Credits remain part of visible answers and retained evidence.

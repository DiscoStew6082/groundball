# Prototype the mobile Query Recipe experience

Type: `prototype`
Status: resolved
Blocked by: none

## Question

Which concrete 360-430px dark, launched-window layout makes the editable example question, Query Recipe, focused clarification, compact results, field discovery, evidence, and export feel like one approachable Ground Ball application while keeping advanced power progressively disclosed?

## Answer

Use the approved Variant F answer-first sports-feed layout. Preserve the website-compatible launched-window frame, make the yellow `GB` control at the top left the single expandable application-navigation trigger, and keep Query, Evidence, History, and Architecture progressively disclosed beneath it. Keep the familiar fixed chat composer at the bottom with only the question field and send button; present compact verified results in the main feed; and place evidence, Query Recipe details, calculations, provenance, and export behind the single Details surface. Clarifications appear inline above the composer rather than sending the user to a separate interface. Field discovery enters through the top-left navigation and Details surface; Ticket 02 owns its exact catalog-driven interaction so it does not add permanent controls to the answer feed.

The selected 390 x 844 captures have no page-level horizontal overflow, and the navigation supports focus entry, selection, Escape, outside-click dismissal, and focus restoration. The approved prototype is recorded by commits `244815d`, `2b0f3b8`, and `03acd0f` on `wayfinder/queryable-ground-ball`, with the final states under `web/prototype-screenshots/F-*.png`.

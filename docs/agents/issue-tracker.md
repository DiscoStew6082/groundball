# Issue tracker: Local Markdown

Ground Ball tracks Wayfinder efforts under `.scratch/<effort>/`.

## Wayfinding operations

- Map: `.scratch/<effort>/map.md`
- Child ticket: `.scratch/<effort>/issues/NN-<slug>.md`
- Each ticket records Type, Status, and Blocked by.
- The frontier consists of open, unblocked, unclaimed tickets in numeric order.
- Claim a ticket by setting Status to claimed before beginning work.
- Resolve it by adding an Answer, setting Status to resolved, and appending its linked gist to the map's Decisions so far.

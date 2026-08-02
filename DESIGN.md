# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-08-02
- Primary product surfaces: CMRE WebUI launcher and Runtime Debug Console
- Evidence reviewed: `tools/cmre-webui/webui/index.html`, `tools/cmre-webui/webui/styles.css`, `tools/cmre-webui/webui/app.js`, `tools/cmre-webui/server.py`, `tools/galaxy-vibe/galaxy_repl.py`, `tools/galaxy-vibe/kernel/function-registry.json`

## Brand
- Personality: quiet, technical, operational, and trustworthy
- Trust signals: explicit session state, typed function metadata, request IDs, response payloads, and visible error codes
- Avoid: marketing hero layouts, decorative gradients, hidden side effects, and arbitrary code execution controls

## Product goals
- Goals: let an operator resume a running SC2 session, discover registered functions, invoke typed functions, run bounded VM programs, and inspect every call/result without restarting the game
- Non-goals: replacing the map launcher, exposing arbitrary Galaxy reflection/eval, or hiding debug-only side effects behind generic buttons
- Success signals: a real call appears in the trace with args, response, status, and request correlation; a VM program can be run through the same session

## Personas and jobs
- Primary personas: map/mod developer debugging a live SC2 session
- User jobs: test one function quickly, inspect a failed response, repeat a VM program, and resume work after reconnecting the browser
- Key contexts of use: desktop browser beside SC2, local-only WebUI, long-lived non-realtime or API-debug sessions

## Information architecture
- Primary navigation: existing launcher tabs plus a `运行时调试` tab
- Core routes/screens: launcher configuration; runtime session toolbar; function catalog; call editor; VM editor; trace timeline; selected response detail
- Content hierarchy: session health first, action controls second, trace and payload evidence third

## Design principles
- Evidence over decoration: every visible action should map to a request or an explicit local VM operation
- Dense but legible: use stable columns, monospace payloads, and compact rows for repeated inspection
- Fail closed: debug-only functions are labeled and still validated by the existing registry
- Tradeoffs: the console favors local developer observability over mobile-first editing, while remaining usable at narrow widths

## Visual language
- Color: reuse CMRE deep navy background, blue borders, gold primary actions, green success, and red errors
- Typography: existing Microsoft YaHei/PingFang SC UI font; monospace for IDs, arguments, and JSON
- Spacing/layout rhythm: 4/8/10px rhythm, short controls, no oversized headings
- Shape/radius/elevation: existing 3-4px radii and restrained borders; no nested decorative cards
- Motion: only short status and row transitions; respect reduced-motion preferences
- Imagery/iconography: no new imagery; use text labels and existing controls because this is an operational tool

## Components
- Existing components to reuse: topbar, tabs, cards, buttons, field selects, output/log panel, status messaging
- New/changed components: runtime session toolbar, function catalog list, typed argument editor, VM program editor, trace table, response inspector
- Variants and states: disconnected, connecting, connected, busy, success, rejected, timeout, empty catalog, and invalid JSON
- Token/component ownership: `tools/cmre-webui/webui/styles.css` owns visual tokens and runtime component styles

## Accessibility
- Target standard: practical WCAG AA for local developer tooling
- Keyboard/focus behavior: all controls are native buttons/inputs; selected function and trace rows are keyboard reachable
- Contrast/readability: success and error states use text plus color; payloads remain selectable
- Screen-reader semantics: use labels, table headers, status `aria-live`, and descriptive buttons
- Reduced motion and sensory considerations: disable non-essential transitions under `prefers-reduced-motion`

## Responsive behavior
- Supported breakpoints/devices: desktop first, usable down to 760px browser width
- Layout adaptations: runtime columns collapse into a single vertical flow; trace remains horizontally scrollable
- Touch/hover differences: controls keep visible labels and do not depend on hover-only information

## Interaction states
- Loading: session and call buttons show busy text while preserving the last trace
- Empty: explain that a session must be connected or no trace exists yet
- Error: show HTTP error and structured RPC error payload without clearing prior evidence
- Success: append a trace row and select it automatically
- Disabled: block invoke/VM controls until connected or while a conflicting operation is active
- Offline/slow network, if applicable: poll status remains explicit and reconnect is manual

## Content voice
- Tone: concise, factual, developer-facing Chinese
- Terminology: distinguish `函数`, `Behavior`, `Ability`, `VM`, `session`, `request_id`, and `error_code`
- Microcopy rules: state what happened and why; never imply a simulator result is native runtime evidence

## Implementation constraints
- Framework/styling system: existing Python standard-library HTTP server and vanilla HTML/CSS/JavaScript
- Design-token constraints: extend existing CSS variables; do not add a second theme
- Performance constraints: catalog is bounded by the explicit registry; trace is capped in the browser and backend
- Compatibility constraints: local Windows Python/PowerShell/SC2 API; no new dependencies
- Test/screenshot expectations: API smoke must prove catalog + session endpoint shape; browser smoke must load the runtime tab and exercise the local catalog path

## Open questions
- [ ] Add a persistent event stream for cross-browser trace sharing if more than one operator needs the same session
- [ ] Add typed form widgets for fixed/integer/boolean/array arguments after the JSON editor proves the MVP flow

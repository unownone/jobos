# Design

<!-- impeccable:design-schema 1 -->

Two surfaces, two worlds. Authenticated Hub stays a dispatch blotter. Public `/` and `/start` are an industrial terminal-ops chassis. Do not mix them.

## Hub (Operate) — `/board` and operator pages

Dispatch blotter: manila paper field, carbon ink, navy ballpoint actions, rubber-stamp status, dark wood rail and phone dock. One open ticket. The phone is a pocket blotter, not a squashed desktop.

### Color

- Paper `--paper` `#ebe6dc`, panel `#faf7f2`, ink `#1a1714`, muted `#5c564c` (tinted from the paper, not gray).
- Wood chrome `#1c1814` / `#2a241e`.
- Primary `--navy` `#1e3a5f`.
- Semantic stamp colors: good `#0f6e56`, warn `#8a5a10`, bad `#9b2c1f`.
- Strategy: Restrained. Accent only on primary actions, selection, and live status.

### Type

- UI: system sans (`ui-sans-serif`, Segoe UI, Roboto). Operate mode; no display face.
- Data/IDs: `ui-monospace`.
- Scale is stepped rem, not fluid headings. Body ~15px / 1.45.

### Layout

- Desktop: 76px left rail + stage. Board is presence | blotter | ticket.
- Phone (≤959px): rail hidden, 4-item dock, Jobs/Live switch, ticket as a bottom sheet over a backdrop.
- Tables become labeled cards at ≤720px.
- Safe-area padding on dock and sheets. Touch targets ≥44px.

### Components

- Buttons: filled navy, outlined secondary, stamp-red danger.
- Pills: outlined stamps, transparent fill.
- Ticket panels: perforated left edge.
- Focus: 2px navy ring. Selection: `#d5deea`.
- Motion: 200ms sheet ease; reduced-motion disables transitions.

### Assets

- Brand rasters: `/brand/mascot.png`, `/brand/logo.png`, `/brand/favicon.png`.
- Shared CSS/JS: `/static/hub.css`, `/static/hub.js`.

## Public landing (Persuade) + get-started (Read)

Night-shift instrument console. Dark navy chassis, amber phosphor at page scale, dashed stitch from the beetle, condensed industrial display. Not a recruiting marketplace and not the blotter.

### Color

- Chassis `--chassis` `#0b1220`, `--chassis-2` `#101827`, panel `--panel` `#172033`.
- Ink `--ink` `#f3eee3`, dim `--ink-dim` `#cbb892` (amber-tinted, not gray).
- Amber `--amber` `#e0992d`, `--amber-hot` `#f3bc5a` (committed: display, primary actions, stitch, live rail).
- Semantic: good `#3f9d7a`, warn `#c9893a`, bad `#c45c4a`.
- Strategy: Committed. Amber owns regions, not only chips.

### Type

- Display: self-hosted **Big Shoulders Display** 700/800. Hero `clamp(2.6rem, 7vw, 5.4rem)`, tracking ≥ `-0.03em`.
- Body: self-hosted **Red Hat Text** 400/500/600. ~17px / 1.5, measure ~70ch.
- Data/commands: self-hosted **Red Hat Mono**.
- Files: `/static/fonts/*.woff2` (OFL).

### Layout

- Sticky mast, then two-column hero (type + beetle/console) until 880px.
- Capabilities are a datasheet (`dl.spec`), not a card grid.
- Hunt loop is a 5-stage rail (vertical stack ≤880px) plus Hub vs git ledger planes.
- Get started is a numbered sequence because order is the information.
- Phone ≤520px: mast wraps; touch targets ≥44px; safe-area padding.

### Components

- Primary button: amber fill, chassis text, offset shadow (not a zero-blur block).
- Ghost: amber hairline.
- Focus: 2px amber ring. Selection: amber on chassis.
- Console plate: dashed amber stitch, `$` prompt in good, commands in amber-hot.
- Motion: one pipeline heat sweep when `#loop-rail` enters view; `prefers-reduced-motion` disables it.

### Assets

- Same brand rasters. Public CSS/JS: `/static/public.css`, `/static/public.js`.
- Do not load `hub.css` on `/` or `/start`.

# Design

<!-- impeccable:design-schema 1 -->

Operator Hub visual system, recorded from the shipped blotter UI in `board/app/static/`.

## World

Dispatch blotter: manila paper field, carbon ink, navy ballpoint actions, rubber-stamp status, dark wood rail and phone dock. One open ticket. The phone is a pocket blotter, not a squashed desktop.

## Color

- Paper `--paper` `#ebe6dc`, panel `#faf7f2`, ink `#1a1714`, muted `#5c564c` (tinted from the paper, not gray).
- Wood chrome `#1c1814` / `#2a241e`.
- Primary `--navy` `#1e3a5f`.
- Semantic stamp colors: good `#0f6e56`, warn `#8a5a10`, bad `#9b2c1f`.
- Strategy: Restrained. Accent only on primary actions, selection, and live status.

## Type

- UI: system sans (`ui-sans-serif`, Segoe UI, Roboto). Operate mode; no display face.
- Data/IDs: `ui-monospace`.
- Scale is stepped rem, not fluid headings. Body ~15px / 1.45.

## Layout

- Desktop: 76px left rail + stage. Board is presence | blotter | ticket.
- Phone (≤959px): rail hidden, 4-item dock, Jobs/Live switch, ticket as a bottom sheet over a backdrop.
- Tables become labeled cards at ≤720px.
- Safe-area padding on dock and sheets. Touch targets ≥44px.

## Components

- Buttons: filled navy, outlined secondary, stamp-red danger.
- Pills: outlined stamps, transparent fill.
- Ticket panels: perforated left edge.
- Focus: 2px navy ring. Selection: `#d5deea`.
- Motion: 200ms sheet ease; reduced-motion disables transitions.

## Assets

- Brand rasters: `/brand/mascot.png`, `/brand/logo.png`, `/brand/favicon.png`.
- Shared CSS/JS: `/static/hub.css`, `/static/hub.js`.

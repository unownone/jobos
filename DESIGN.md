# Design

<!-- impeccable:design-schema 1 -->

One visual world: industrial terminal-ops. Public landing persuades; Hub operates. Same chassis, amber, type, and tokens. Tokens live in `board/app/static/theme.css`. Surfaces must not re-declare the palette.

## World

Night-shift instrument console. Dark navy chassis under warm instrument light. Amber phosphor at page scale (display type, primary actions, stitch dashes, live status). Dashed amber stitch from the beetle. Not a recruiting marketplace, not manila blotter, not a second theme.

## Color

Source: `:root` in `/static/theme.css`.

- Chassis `--chassis` `#0b1220`, `--chassis-2` `#101827`, panel `--panel` `#172033`, bezel `--bezel` `#243044`.
- Ink `--ink` `#f3eee3`, dim `--ink-dim` `#cbb892` (amber-tinted, not gray).
- Amber `--amber` `#e0992d`, `--amber-hot` `#f3bc5a` (committed: buttons, rules, stitch, focus, selection).
- Semantic: good `#3f9d7a`, warn `#c9893a`, bad `#c45c4a`.
- Aliases Hub still reads: `--paper` → chassis, `--navy` → amber, `--wood` → chassis, `--muted` → ink-dim.
- Strategy: Committed. Amber owns regions and primary actions.

## Type

- Display: self-hosted **Big Shoulders Display** 700/800 (hero, Hub top title, auth h1).
- UI/body: self-hosted **Red Hat Text** 400/500/600. Hub body ~15px / 1.45; landing ~17px / 1.5.
- Data/commands: self-hosted **Red Hat Mono**.
- Files: `/static/fonts/*.woff2` (OFL).

## Layout

- Public: sticky mast, two-column hero until 880px, datasheet capabilities, 5-stage loop rail.
- Hub Operate: 76px left rail + stage. Board is presence | list | ticket. Phone ≤959px: rail hidden, 4-item dock, Jobs/Live switch, ticket as a bottom sheet. Tables become labeled cards at ≤720px.
- Shared: `--radius` 2px, `--touch` 44px, safe-area padding, dashed amber rules instead of punch-holes.

## Elevation & Depth

- `--shadow`: 0 18px 40px rgba(4, 8, 14, 0.45) — offset + blur.
- `--elev-amber` on primary marketing buttons.
- No zero-offset halos. No inset paper highlight.

## Shapes

- `--radius` 2px on buttons, inputs, panels, chips.
- `--radius-pill` only for the phone Jobs/Live switch.
- `--radius-sheet` for the mobile ticket sheet.

## Components

- Primary button: amber fill, chassis text (`--navy` / `--navy-text` aliases).
- Secondary: panel fill, amber hairline.
- Danger: `--stamp` / `--bad`.
- Status pills: dashed currentColor outline, semantic token colors.
- Focus: 2px amber ring. Selection: amber on chassis. Scrollbar: amber on chassis-2.
- Auth (`body.hub-auth`): same chassis field as landing; ticket panel with dashed stitch.

## Assets

- Brand rasters: `/brand/mascot.png`, `/brand/logo.png`, `/brand/favicon.png`.
- Shared tokens: `/static/theme.css`.
- Surfaces: `/static/public.css` (landing/start), `/static/hub.css` (operator + login/join/signup).

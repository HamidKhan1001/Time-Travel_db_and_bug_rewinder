---
name: Vapor Engine
colors:
  surface: '#faf8ff'
  surface-dim: '#d2d9f4'
  surface-bright: '#faf8ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f3ff'
  surface-container: '#eaedff'
  surface-container-high: '#e2e7ff'
  surface-container-highest: '#dae2fd'
  on-surface: '#131b2e'
  on-surface-variant: '#464555'
  inverse-surface: '#283044'
  inverse-on-surface: '#eef0ff'
  outline: '#777587'
  outline-variant: '#c7c4d8'
  surface-tint: '#4d44e3'
  primary: '#3525cd'
  on-primary: '#ffffff'
  primary-container: '#4f46e5'
  on-primary-container: '#dad7ff'
  inverse-primary: '#c3c0ff'
  secondary: '#712ae2'
  on-secondary: '#ffffff'
  secondary-container: '#8a4cfc'
  on-secondary-container: '#fffbff'
  tertiary: '#005338'
  on-tertiary: '#ffffff'
  tertiary-container: '#006e4c'
  on-tertiary-container: '#7df1bd'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e2dfff'
  primary-fixed-dim: '#c3c0ff'
  on-primary-fixed: '#0f0069'
  on-primary-fixed-variant: '#3323cc'
  secondary-fixed: '#eaddff'
  secondary-fixed-dim: '#d2bbff'
  on-secondary-fixed: '#25005a'
  on-secondary-fixed-variant: '#5a00c6'
  tertiary-fixed: '#85f8c4'
  tertiary-fixed-dim: '#68dba9'
  on-tertiary-fixed: '#002114'
  on-tertiary-fixed-variant: '#005137'
  background: '#faf8ff'
  on-background: '#131b2e'
  surface-variant: '#dae2fd'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 36px
    fontWeight: '600'
    lineHeight: 44px
    letterSpacing: -0.03em
  display-lg-mobile:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.025em
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: -0.005em
  body-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0em
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  code-lg:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: -0.01em
  code-md:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: -0.005em
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0em
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.04em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-tablet: 0.75rem
  gutter-mobile: 0.5rem
  margin: 1.5rem
  margin-mobile: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1.25rem
  space-xl: 2rem
---

## Brand & Style
The design system positions itself at the apex of next-generation developer tooling: hyper-precise, engineered, and uncompromisingly aesthetic. Tailored for engineers, infrastructure architects, and system platform leads, the UI rejects utilitarian drabness in favor of purposeful radiance. It balances extreme density with luminous clarity, drawing aesthetic cues from contemporary high-craft execution standards seen in tools like Linear and Stripe.

The visual dialect merges modern technical minimalism with deliberate tactile luminescence:
- **Crisp Structural Discipline:** Sharp hierarchy, micro-hairlines, dense monospaced readouts, and surgical alignment.
- **Micro-Luminescent Radiance:** Elevated white interactive surfaces floating above a cool zinc bedrock, accented by controlled glow halos and vibrant chromatic state markers.
- **High-Acuity Functional Color:** Color is never decorative; it operates as an operational telemetric signal—separating production branches, active databases, verified assertions, and syntax states with pinpoint authority.

## Colors
The system employs an intentional light palette built on a layered architectural substrate: pure white containers (`#ffffff`) resting upon a cool slate/zinc foundation canvas (`#f8fafc` grading into `#f1f5f9`). Structural containment relies on razor-thin slate dividers (`#e2e8f0` to `#cbd5e1`).

### Semantic Telemetry Palette
- **Primary (Electric Indigo/Violet - `#4f46e5` / `#6366f1`):** Serves as the primary operational driver, focus indicators, execution actions, and active navigation nodes.
- **Secondary (Iris / Clone Branching - `#7c3aed` / `#8b5cf6` with soft wash `#f5f3ff`):** Dedicated to branch isolation, staging clusters, clone environments, and non-destructive sandbox states.
- **Success / Verified (Emerald / Seafoam - `#059669` / `#10b981` with soft wash `#ecfdf5`):** Denotes healthy deployments, passing health checks, verified commits, and cryptographically signed builds.
- **Warning / Divergence (Honey Amber - `#d97706` / `#f59e0b` with soft wash `#fef3c7`):** Marks uncommitted schema deltas, pending migrations, and concurrency bottlenecks.
- **Critical / Production Warning (Punchy Crimson / Rose - `#e11d48` / `#f43f5e` with soft wash `#fff1f2`):** Reserved for live database writes, schema-dropping risk thresholds, terminated pods, and telemetry alarms.

### Neutral & Text Matrix
- **Text Primary (`#0f172a`):** Deep navy slate delivering optimal legibility for critical telemetry, metrics, and interactive titles.
- **Text Secondary (`#334155`):** Subdued charcoal for structural descriptions, table headers, and inactive inputs.
- **Text Muted / Tertiary (`#64748b`):** Balanced slate for inline code parameters, metadata, timestamps, and path breadcrumbs.

## Typography
Typography creates an instant cognitive separation between prose context and raw execution code. 

- **Primary Interface Font (`Inter`):** Chosen for its tall x-height, neutral tone, and exceptional clarity under tight informational densities. Used across structural headings, modal narratives, tables, and navigation elements. Headings feature subtle negative tracking (`-0.01em` to `-0.03em`) to deliver a crisp, authoritative presence.
- **Monospaced Telemetry Font (`JetBrains Mono`):** Powers all data-dense representations: commit hashes, database table references, API routes, terminal outputs, and system metrics. Its distinctive ligatures, open counters, and generous punctuation marks guarantee instant identification of brackets, colons, and numerical values.

## Layout & Spacing
The layout architecture utilizes an adaptable fluid-grid system designed for sustained multi-monitor workflows and dense dashboard split-views.

- **Grid Architecture:** Desktop views operate on a 12-column variable fluid grid with a standard `1rem` (16px) gutter and `1.5rem` (24px) canvas containment margin. Dense data panes (such as table viewports, execution logs, and schema maps) can break out into full-width edge-to-edge sub-canvases.
- **Component Rhythms:** Internal padding respects strict vertical and horizontal steps: micro-spacing (`0.25rem` / 4px) for badge and input padding, tight spacing (`0.5rem` / 8px) for list groups, standard spacing (`0.75rem` / 12px) for card interiors and form gaps, and wider margins (`1.25rem`–`2rem`) for macroscopic container boundaries.
- **Breakpoints:**
  - **Desktop (1024px+):** Full multi-pane workspace with persistent navigation sidebars, dual-pane execution editors, and contextual toolbars.
  - **Tablet (768px - 1023px):** Sidebars collapse into docked icon rails; grid shifts to 8 columns with `0.75rem` gutters.
  - **Mobile (< 768px):** Single-column stack with `0.5rem` gutters and `1rem` margins; dense tables convert into inspectable card records.

## Elevation & Depth
Depth in this design system avoids heavy, muddy drop shadows. Instead, it relies on crisp optical layering: white floating volumes anchored by micro-hairline borders and luminous, diffuse ambient light.

- **Base Surface Tier:** The underlying application backdrop rests at `#f8fafc` or `#f1f5f9`.
- **Card & Container Elevation (Level 1):** Solid `#ffffff` containers with a microscopic single-pixel border (`1px solid #e2e8f0`). The elevation is defined by an ultra-subtle composite shadow: `0 1px 3px rgba(15, 23, 42, 0.04), 0 1px 2px rgba(15, 23, 42, 0.02)`.
- **Interactive & Dropdown Floating Tier (Level 2):** Command palettes, flyout popovers, and contextual dropdowns hover with higher separation: `0 10px 15px -3px rgba(15, 23, 42, 0.06), 0 4px 6px -4px rgba(15, 23, 42, 0.03)` with a hairline boundary of `#cbd5e1`.
- **Inner Glow / Edge Polishing:** Premium card surfaces and active focus containers feature an interior reflection using an inset hairline box shadow (`inset 0 1px 0 0 rgba(255, 255, 255, 0.9)`), creating the tactile feel of beveled optical glass without skeuomorphic bulk.
- **Telemetry Glow Accents:** Active connection status pings, focused terminal borders, and primary interactive elements utilize a soft chromatic back-glow: `0 0 0 3px rgba(99, 102, 241, 0.15)` for indigo states and `0 0 0 3px rgba(16, 185, 129, 0.18)` for healthy status beads.

## Shapes
The shape philosophy favors engineered compactness: `roundedness: 1` sets a disciplined baseline corner radius of `0.25rem` (4px) for controls, `0.5rem` (8px) for containers and cards, and `0.75rem` (12px) for root application modals.

- **Inputs, Buttons, and Micro-badges:** Calibrated at `0.25rem` (4px). This tight curvature maximizes usable tabular space, preserves strict vertical alignment across code blocks, and retains a clean technical edge.
- **Cards, Panels, and Previews:** Sculpted at `0.5rem` (8px). This creates gentle structural rhythm against the background canvas without feeling soft or toy-like.
- **Pill Exception for Status Indicators:** Runtime beads, active thread pills, and live branch indicators may utilize full pill radii (`9999px`) strictly to differentiate persistent physical hardware status from actionable modular cards.

## Components

### Buttons
- **Primary Action:** Solid electric indigo background (`#4f46e5`) with pure white text (`#ffffff`), featuring a 1px border (`#4338ca`) and a subtle top-edge inset highlight (`inset 0 1px 0 rgba(255, 255, 255, 0.2)`). Hover triggers a shift to `#4338ca` accompanied by an indigo ambient halo (`0 2px 8px rgba(79, 70, 229, 0.35)`).
- **Secondary Action:** Crisp white surface (`#ffffff`) with text in primary navy slate (`#0f172a`), bound by a 1px border (`#e2e8f0`). Hover yields a slate-tinted background (`#f8fafc`) and border tint (`#cbd5e1`).
- **Destructive Action:** Subtle crimson wash (`#fff1f2`) with sharp crimson text (`#e11d48`) and border (`#fecdd3`). On hover, transitions to solid crimson (`#e11d48`) with white text.

### Chips & Telemetry Badges
- **Architecture:** Compact geometry composed of `JetBrains Mono` text (`10px` or `11px`), tight padding (`2px 6px`), with a 1px border and matched soft chromatic background.
- **Verified / Success:** `#ecfdf5` background, `#059669` text, `#a7f3d0` border, preceded by an active green status node (`#10b981`).
- **Clone / Branch:** `#f5f3ff` background, `#7c3aed` text, `#ddd6fe` border, displaying a distinct Git branch glyph.
- **DB Warning / Live Ops:** `#fff1f2` background, `#e11d48` text, `#fecdd3` border, featuring a pulsing ping indicator.

### Input Fields & Search Bars
- **Default State:** Pure white background (`#ffffff`), border in `#e2e8f0`, text in `#0f172a`, with muted placeholder text (`#94a3b8`). Height constrained to `32px` or `36px` for optimal density.
- **Focus State:** Border shifts instantly to electric indigo (`#6366f1`) coupled with a localized outer glow: `0 0 0 3px rgba(99, 102, 241, 0.12)`.
- **Monospaced Input Variant:** Used for connection strings, environment variables, and branch names; switches font directly to `JetBrains Mono` at `12px` with a slate wash background (`#f8fafc`).

### Checkboxes & Radio Controls
- **Geometry:** Micro-scale square (`14px x 14px`) with `2px` corners for checkboxes; circular (`14px`) for radios.
- **Resting:** 1px border (`#cbd5e1`) on pure white (`#ffffff`).
- **Checked:** Filled with primary indigo (`#4f46e5`), crisp white inner icon, and supported by a subtle indigo outline glow.

### Cards & Data Panels
- **Structure:** Crisp white background (`#ffffff`), `0.5rem` border-radius, bordered with `1px solid #e2e8f0`.
- **Card Header:** Separated via a horizontal divider (`1px solid #f1f5f9`), featuring a clear title in `Inter 14px SemiBold` paired with an environment/branch badge on the trailing edge.
- **Inner Edge Treatment:** Integrated top hairline highlight (`inset 0 1px 0 rgba(255, 255, 255, 1)`) ensuring immediate distinction when nested within secondary gray canvases.

### Terminal & Log Stream Viewer
- **Structure:** Dedicated light-slate container (`#f8fafc`) bordered by `#e2e8f0`. Left-hand column features static line numbering in muted slate (`#94a3b8`).
- **Log Stream Items:** Rendered in `JetBrains Mono 12px` with absolute baseline alignment. Color-coded log level tags (`[INFO]` in `#4f46e5`, `[WARN]` in `#d97706`, `[CRIT]` in `#e11d48`) providing immediate visual telemetry scanning.
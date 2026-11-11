> Historical architecture notes from upstream SiteSurgeon. See the root README for the current VisualDetox provider and workflow.

# SiteSurgeon — Design Decisions

**Concept: Inspection Report.** SiteSurgeon examines a page and produces evidence.
The interface should feel like a precise markup review — not an AI app — so every
screen uses the visual language of technical documentation: numbered markers,
hairline rules, ledger tables, captions under figures, not over them.

**Colour.** Paper off-white `#F7F6F2` surface, near-black ink `#18181B`, secondary
text `#71717A`. One accent: redline annotation red `#C0392B` used only for issue
markers, not-verified status, and destructive actions. Primary buttons are ink
black. No gradients, no glow, no neon.

**Typography.** Newsreader (serif, self-hosted) for headings, result numbers, and
captions — it reads like editorial copy. Inter (sans, variable, self-hosted) for
all UI text. JetBrains Mono (self-hosted) for measurements, selectors, durations,
and run metadata. Labels use letterspaced small-caps (`font-variant: small-caps`).

**Layout.** Single 1100px max-width container, 24px gutters, 8px spacing grid.
Header, hero, home grid, and result sections all share the same left edge. No
cards inside cards. Hairline `1px solid #E4E4E7` borders instead of shadows.

**Motion.** 150–250ms ease-out. Fade-up on load. Count-up on the result number.
SVG check strokes draw themselves. Issue rows slide in staggered. Redline markers
draw in with a circle-expand animation. Row↔marker cross-highlight on hover.
Reduced-motion: all animation disabled.

**Slider.** Before/After labels live *outside* the image frame as captions
("Fig. 1: Desktop, before" / "Fig. 1: Desktop, after"). The divider handle is a
thin redline-red line with a small circle. Auto-plays on home hero, pauses on
hover, keyboard-accessible with arrow keys.

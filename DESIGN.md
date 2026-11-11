---
name: VisualDetox
description: A design system for auditing webpages and reviewing visual evidence.
colors:
  primary: "#275e3f"
  evergreen: "#17291f"
  evergreen-hover: "#244432"
  evergreen-edge: "#34503f"
  lime: "#e0f7ab"
  error: "#922e32"
  paper: "#f6f7f0"
  surface: "#fffefa"
  ink: "#19271e"
  ink-secondary: "#3c5142"
  ink-muted: "#556b5a"
  line: "#d7e0d0"
  sage: "#eaf0e4"
  sage-control: "#e6eddf"
  sage-hover: "#dce8d5"
  inverse-ink: "#f7f9f1"
  evidence-ink: "#f1f6e9"
typography:
  display:
    fontFamily: "Newsreader, Georgia, serif"
    fontSize: "6rem"
    fontWeight: 400
    lineHeight: 0.9
    letterSpacing: "-.04em"
  headline:
    fontFamily: "Newsreader, Georgia, serif"
    fontSize: "5.5rem"
    fontWeight: 400
    lineHeight: 0.96
    letterSpacing: "-.035em"
  title:
    fontFamily: "Newsreader, Georgia, serif"
    fontSize: "3.6rem"
    fontWeight: 400
    lineHeight: 1.04
    letterSpacing: "-.025em"
  body:
    fontFamily: "Segoe UI, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Segoe UI, system-ui, sans-serif"
    fontSize: ".875rem"
    fontWeight: 650
  metadata:
    fontFamily: "JetBrains Mono, monospace"
    fontSize: ".69rem"
    lineHeight: 1.45
rounded:
  pill: "99px"
  capsule: "999px"
  field: "30px"
  input: "26px"
  evidence: "24px"
  comparison: "17px"
  report: "14px"
  capture: "13px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.evergreen}"
    textColor: "{colors.inverse-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "9px 17px"
  button-primary-hover:
    backgroundColor: "{colors.evergreen-hover}"
  button-secondary:
    backgroundColor: "{colors.sage-control}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "9px 17px"
  button-secondary-hover:
    backgroundColor: "{colors.sage-hover}"
  button-text:
    backgroundColor: "transparent"
    textColor: "{colors.primary}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "9px 17px"
  audit-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "5px"
  site-header:
    backgroundColor: "{colors.sage}"
    textColor: "{colors.ink}"
    rounded: "{rounded.capsule}"
    padding: "8px 15px 8px 19px"
  evidence-panel:
    backgroundColor: "{colors.evergreen}"
    textColor: "{colors.evidence-ink}"
    rounded: "{rounded.evidence}"
  report-tabs:
    backgroundColor: "{colors.sage-control}"
    rounded: "{rounded.pill}"
    padding: "{spacing.xs}"
  report-tab-selected:
    backgroundColor: "{colors.evergreen}"
    textColor: "{colors.surface}"
    rounded: "{rounded.pill}"
    padding: "9px 15px"
---

# Design System — VisualDetox

## Overview

**Creative North Star: "The Audit Desk"**

VisualDetox is an Operate surface for frontend engineers. Newsreader headlines give the workspace an editorial rhythm. Paper and sage ground the controls, and an evergreen pane gives saved captures their own space.

**Key Characteristics**

- URL-first entry with a real saved comparison alongside it.
- Flat rows and visible measurements for reviewing audit results.
- Short interaction feedback and visible keyboard focus.

## Colors

Moss green carries text actions, light-surface focus, and successful checks. Evergreen marks the main actions and frames the evidence pane. Lime makes the comparison divider and dark-surface focus visible and accents the verified status. Red identifies failed checks and removed-line counts.

Paper is the page ground. The near-white surface holds form fields and report content. Sage fills the header and segmented controls, with a slightly deeper sage for hover. Green-gray ink steps down from headlines to supporting copy and metadata. Use the light rule for rows and the evergreen edge inside the evidence pane.

## Typography

Use regular Newsreader for display, report, and section headings. The homepage display size uses `clamp(4rem, 7vw, 6rem)`, then `clamp(3.5rem, 8vw, 5rem)` at 950px and `clamp(3.1rem, 11vw, 5.3rem)` at 767px. The italic second line carries the moss accent. Report titles use `clamp(3rem, 6vw, 5.5rem)` and section titles use `clamp(2.4rem, 4vw, 3.6rem)`.

Segoe UI handles prose, navigation, and controls. Keep introductory copy within 40ch. Use JetBrains Mono for capture dimensions, comparison labels, issue indices, elapsed time, and diffs. Measurements use tabular numerals.

## Layout

Cap the container at 1220px with 48px minimum side gutters. The desktop hero divides into `.88fr` for the URL form and `1.12fr` for the saved comparison. Keep the 470px-wide form under the heading and the alternate entry points below the form.

At 950px, use 28px gutters. At 767px, use 16px gutters and stack the hero and supporting columns in reading order. Reflow issue rows from a table into a compact stack of description, measurement, checks, and status beside the issue index. At 360px, tighten the wordmark and header navigation gaps.

## Elevation & Depth

Sage fills and fine rules divide the supporting sections and ledger rows. The evergreen evidence pane uses a single diffuse shadow (`0 26px 58px -34px #1a412b80`). The comparison thumb uses a small shadow (`0 2px 8px #17291f50`) over the capture.

## Shapes

Use capsules for the header, actions, and tabs. Round the URL field and nest a pill-shaped submit button beside it. Step the radius down from the evidence pane to the image frame. Use lightly rounded containers for reports and flat rules between rows.

## Components

- **URL field and actions.** Pair a visible Page URL label with the URL input and evergreen Run audit button. Give regular action buttons a 44px minimum height. The audit button carries a 34px lime arrow disc. Use sage for secondary actions and underlined hover treatment for text actions. Place URL feedback below the field.
- **Saved comparison.** Show the saved run name, viewport dimensions, and aligned before-and-after captures. Keep the Before and After labels visible. Put the verified status and report action below a divider. Use a native range input, start at 50%, and announce the visible before percentage as it changes. Preserve pointer, touch, and keyboard operation.
- **Report tabs.** Use a sage track with an evergreen selected pill for Desktop, Mobile, and Changes. Keep one tab in the tab order, move selection with the Left and Right arrow keys, and support Home and End. Associate the selected tab with its panel.
- **Issue ledger.** Present measurement, checks, and status with each issue. Pair status color with text and keep the comparison and ledger readable at mobile widths.
- **Focus and motion.** Use a 2px moss focus outline with a 4px offset on light controls. Use lime on evergreen and outline the comparison frame when its range input has focus. Button feedback lasts 200ms and arrow movement lasts 240ms. The progress spinner runs while a step is active. Honor `prefers-reduced-motion`.

## Do's and Don'ts

- **Do** keep the URL field and Run audit together as the primary entry point.
- **Do** use real captures with matching dimensions for each comparison.
- **Do** pair every check color with a readable label and keep focus visible on both light and dark surfaces.

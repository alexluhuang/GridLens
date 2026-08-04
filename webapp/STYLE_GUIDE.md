# GridLens Web Style Guide

This style guide defines the NYCTA-manual-inspired visual system for the GridLens web client.

## Visual Direction

- Monochrome first: black, white, and neutral gray
- No gradients
- No glassmorphism or blur
- Strong borders and rectangular framing
- Minimal ornament with emphasis on structure and legibility

## Brand

- Primary logo asset: `webapp/public/gridlens.svg`
- Use the full logo in header and major branded surfaces
- Do not apply colored glows, gradients, or drop shadows to the logo

## Color Tokens

Light mode:

- Page background: `#f7f7f5`
- Panel background: `#ffffff`
- Primary text: `#101010`
- Secondary text: `#4d4d4d`
- Main border: `#1a1a1a`
- Secondary border: `#cfcfc9`
- Accent/action fill: `#111111`
- Accent text on fill: `#f8f8f8`

Dark mode:

- Page background: `#0b0b0b`
- Panel background: `#141414`
- Primary text: `#f4f4f1`
- Secondary text: `#c9c9c4`
- Main border: `#f0f0eb`
- Secondary border: `#666666`
- Accent/action fill: `#ffffff`
- Accent text on fill: `#0b0b0b`

## Typography

- Primary font stack: `"Helvetica Neue", Helvetica, Arial, sans-serif`
- Monospace font stack: `"SFMono-Regular", Consolas, "Liberation Mono", monospace`
- Headings should be bold, compact, and slightly condensed by tracking
- Utility labels and table headers should be uppercase

## Shape Language

- Default radius: `0`
- Panels should read like printed manual modules, not soft cards
- Borders communicate hierarchy more than color fills

## Components

Header:

- Use logo on the left with title and subtitle
- Keep copy concise and operational

Buttons:

- Primary buttons use solid black in light mode and solid white in dark mode
- Secondary buttons are white or panel-colored with visible border

Theme toggle:

- Segmented control with no gradient
- Active segment inverts foreground/background

Charts:

- Transparent chart backgrounds inside white or black-framed containers
- Neutral axes and labels
- Highlight data through contrast, not decorative color systems

Tables:

- Uppercase headers
- Tight grid lines
- Strong left alignment and readable spacing

## Interaction Principles

- Keep the interface functional and restrained
- Prefer explicit state changes over animated flourish
- Use selection states with border/fill contrast, not bright color

## Implementation Notes

- Core tokens live in `webapp/src/styles.css`
- The header and branding lockup live in `webapp/src/App.tsx`
- When adding new components, reuse the existing CSS variables instead of introducing new ad hoc colors

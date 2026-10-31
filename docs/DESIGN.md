# Dashboard design notes

Written before the frontend was built, revised after reviewing it in the browser.

## Who it is for

An engineer, usually a reviewer, who has a branch or a pull request in front of them and
wants to know within seconds: is this safe to merge, and if not, what exactly should I
test? They read diffs all day. They are not looking for a pretty chart; they want the
answer, the evidence, and a checklist.

## Principles

1. **The answer comes first.** The top of the page says the level, the score, and the
   one-sentence verdict. Everything below is evidence for that sentence.
2. **Colour means risk, and nothing else.** The chrome is graphite and chalk. The only hues
   on screen are the four risk levels, so a spot of colour always tells you something.
   Every level also has its own shape (circle, triangle, diamond, octagon) and a text label,
   so colour is never the only carrier. This matters for colour-blind readers and for the
   amber, which has poor contrast on a light background.
3. **Show the arithmetic.** The points beside each reason add up to the total, and the score
   is a visible function of them. People trust a number they can audit.
4. **Evidence is quoted, not described.** Each reason shows the real line, with file and line
   number, in the same monospace as a diff. Flagged lines are marked in the diff view, with the
   rule's note under them, the way a review comment would be.
5. **Tests are a checklist, not prose.** The test plan can be ticked off, and remembers what
   you ticked.

## The one bold thing: the risk ruler

The score is not shown on a round gauge. It sits on a ruler, 0 to 100, cut into the four level
bands with the build gate marked on it. A ruler is how a measurement is read, and it lets the
gate ("fails at high, 50") sit on the same scale as the result. It is drawn thin, with a fine
tick every 5 points and labels at the band edges only. The fill grows once on load; nothing
else animates.

## Palette

Neutrals are a cool grey with a slight blue-green lean, which is what keeps them from reading
as default grey. The header band is the darkest thing on the page: an instrument faceplate.

| Role | Light | Dark |
|---|---|---|
| Ground (page) | `#e9ecee` | `#0f1316` |
| Surface (panels) | `#f6f8f9` | `#171c20` |
| Well (tracks, code) | `#e0e5e8` | `#1f262b` |
| Ink | `#12171b` | `#e8edf0` |
| Ink 2 (secondary) | `#444c53` | `#b2bbc1` |
| Ink 3 (muted) | `#66707a` | `#8a949b` |
| Hairline | `#cfd6db` | `#2b343a` |

Risk levels use the data-visualisation palette's fixed status steps in both themes
(`#0ca30c`, `#fab219`, `#ec835a`, `#d03b3b`). Unfilled parts of the ruler use a tint of the same
hue. There is no brand accent colour: primary actions are solid ink.

## Type

One family, the platform's most characterful UI sans: **Bahnschrift** on Windows (a DIN-style
face that fits road-sign and inspection-tag conventions), then Segoe UI Variable, then
`system-ui`. Fonts are never downloaded, so the dashboard has no network dependency and runs
under a strict CSP. Numerals use the font's proportional figures in large sizes (the score) and
tabular figures in tables. Code is Cascadia Mono, then SF Mono, then Consolas.

Scale: 11.5 / 12.5 / 14 / 16 / 20 / 28 / 88 px. Uppercase labels are 11.5px with tracking.

## Layout

```
header band:  mark  ChangeRisk   Report  History  Rules                 theme
toolbar:      base [ main v ] ... head [ feature/x v ]  ( branch | staged | working )  [Analyse]
rail (248px)  | main column (max 980px)
 recent       |   change header         refs, size, time, export
 analyses     |   verdict + ruler        the answer
              |   why this needs extra testing      ranked reasons
              |   test plan              checklist
              |   where the risk is      category bars + trend
              |   changed files          table, diffs inline
```

Under 900px the rail folds above the main column and tables scroll inside their own box.
Nothing scrolls the page sideways.

## What was deliberately left out

* Pie and donut charts, gauges, and gradients. A bar or a ruler reads the same data with less ink.
* A brand colour. See principle 2.
* Icons as decoration. Icons appear only where they replace a word the user needs to find
  quickly (copy, export, theme, expand).
* Emoji, anywhere.
* A framework. The dashboard is about forty small functions over the DOM; a build step and a
  dependency tree would cost more than they save, and the standalone HTML report would not be
  possible without a bundler.

## Accessibility

Keyboard: every control is a real button, link, input or `details`, with a visible focus ring.
Screen readers: landmarks, one `h1`, a polite live region for analysis progress and errors,
`aria-label`s on the shapes. Each chart has a table twin. Respects `prefers-reduced-motion`
and `forced-colors`. Contrast of text on its surface is at least 4.5:1 in both themes.

## Changes made after reviewing it in the browser

The first build went through several review passes against a seeded demo repository, at desktop,
tablet and phone widths, in both themes. What the passes changed:

* **Area bars collapsed to slivers in a narrow panel.** The label column left about 50px for the bar.
  The chart now sizes from its own container: label beside the bar when there is room, label above it
  when there is not.
* **Every file looked "flagged".** A finding about the whole change (size, spread, no tests) was
  charged to each file it listed. Findings now carry a scope, and whole-change findings belong to no
  file, so the file list shows which files actually have problems.
* **The refs in the change header broke across lines** because the action buttons took the width.
  Refs now get their own row; buttons sit with the file counts.
* **The analysis form pushed the report 800px down on a phone.** Under 700px it folds into a
  collapsible section, closed by default. On the History and Rules tabs it is hidden.
* **The phone header clipped the theme switch.** Below 520px the wordmark text is dropped and the mark stays.
* **The "History signals" checkbox forced the Analyse button onto its own row** at laptop widths. It
  moved to the hint line under the form.
* **Severity calibration, driven by what the demo showed.** A production timeout that doubled scored
  High and would fail the default gate. Ordinary config edits now start at Low and production files at
  Medium; only a tenfold jump (or zero) reaches High.
* **A level and a score are both shown but only the score is a number you can argue with**, so the
  "How this score is built" disclosure sits under the ruler instead of in a separate page.

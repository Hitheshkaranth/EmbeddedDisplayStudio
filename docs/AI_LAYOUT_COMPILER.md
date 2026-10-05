# AI Design: planning and compiling the layout

![Before and after: same model, same briefs, rendered by hmi-ui](assets/ai/compiler-before-after.png)

## Why the old pipeline could not produce a good screen

The AI Design tab asked the model for **absolute geometry** (x, y, width,
height for every widget) and then `designer/layout/polish.py` moved that
draft until the critic was satisfied: it snapped widgets to archetype slots,
removed overlaps and added captions. Measured on four briefs against the lab
model (ornith-35b, 2026-10-05):

| Failure | Cause |
|---|---|
| Half the replies became `Partial_ShStatDot` placeholders | One missing quote in a long geometry payload failed `json.loads` for the whole design |
| Faces drew "Gauge", "Button", "Text" | The model wrote `minimumValue`/`label` where the widget takes `minimum`/`title`; the registry filter dropped them |
| Empty bands, clipped labels, a trend chart as the "hero" | Slotting a geometry draft into fixed archetypes cannot recover intent the geometry never carried |
| Value tiles with no caption on the panel | hmi-ui's ShValueTile read `label`; the schema and the Designer write `title` |
| Trend charts painting outside their box, axes upside down | ShTrendChart warning-band formula and axis labels (QML and C) |

Geometry is the part a language model is worst at, and also the longest part
of its reply. The fix is to stop asking for it.

## The new pipeline: plan, then compile

```
brief --> model: content plan (no geometry) --> intake (repair, normalise)
      --> compiler: header + regions + bands + tokens --> hmi-ui / canvas
```

1. **Plan prompt** (`build_plan_prompt` in `tools/hmi_deployer/ai_generator.py`).
   The model says *what* the screen shows: a title, header lamps or nav
   buttons, and 3-6 sections, each with a title, a role (`hero`,
   `instruments`, `readings`, `trend`, `alarms`, `status`, `controls`) and
   widgets with labels, units, ranges, bindings and actions. It may also ask
   for `"size": "compact" | "normal" | "large"` on a section or widget. A
   per-purpose catalogue quotes each widget's real property names, and
   placeholders keep the example from being copied as a design.
2. **Intake** (`designer/layout/intake.py`). This reads the reply the way
   it was meant:
   - Lenient JSON repairs missing quotes, a dropped `"properties": {`,
     unbalanced or early closers, truncation, comments and Python literals.
   - Duplicate keys spill into a new object rather than overwriting, so a
     section whose opening brace became `],` is recovered.
   - Property synonyms are mapped onto the spelling each type takes.
   - Lists are joined where the widget takes text.
   - Icons are mapped onto the 124 kit icons.

   The generator also folds stray sections back into their page, hands
   section-level bindings to the widgets they belong to, merges one-card
   pages that fit on one screen, and maps invented types (`ShLamp`) onto
   real ones.
3. **Compiler** (`designer/layout/compiler.py`). This is deterministic and
   never reads model geometry:
   - **Header:** the title on the left, status lamps and navigation on the
     right, and a hairline rule beneath. Navigation to a missing page or to
     this page is dropped.
   - **Regions:** the body is searched, not templated. It tries every row
     and column partition, hero-left/right/top and hero-centre at several
     fractions, each scored by a cost model:
     - content fit per card;
     - shortfall against each card's minimum size;
     - hero prominence and density;
     - empty cards, slivers and edge count.

     Too many cards for the screen share a card (`section_limit`).
   - **Bands inside a card:** faces sit in rows at one height and are
     evenly spaced. Tiles go on an equal grid, each scaled uniformly from its
     design size so its text never clips. Strips get full-width rows.
     Controls go at the foot: full-row inputs, then switches, then a button
     row sized to the button text. Lamps are labelled lamps on a grid, with
     a compact grid used before anything spills. Charts and tables fill
     what is left.
   - **Minimums first:** slicing gives every card the minimum its content
     needs before sharing the rest out by weight, so a three-button card is
     never a sliver beside a large hero.
   - **No repeated names:** a hero dial's caption folds into its card title,
     a card holding only an alarm table has no heading of its own, tile
     labels lose the card's leading word ("Current" inside "Motor"), and a
     heading too long for its card falls back to its first part.
   - **Density (size constraints):** the same search runs at widget scales
     1.0, 0.9, 0.8, 0.7 and 0.6. Each scale shrinks design sizes, minimums,
     control height and in-card spacing together. A screen keeps its design
     sizes unless shrinking clearly lays it out better (each step costs 2).
     Per-widget `size` wishes multiply in. Controls never go under 32 px,
     and the margin, header and title never shrink.
   - **Semantics:**
     - Stop, Trip and E-Stop buttons become `destructive`, navigation
       buttons `outline`, Reset and Ack `secondary`.
     - A bound gauge shows its live value (an empty `readout`, and
       `readoutUnit` from the binding), and no kit sample unit is left
       showing.
     - Long dial captions are shortened, a hero caption moves to its card
       title, and a trend chart's warning band stays inside its scale.
   - **Plan in the widgets:** every widget carries `_section`
     (`"title|role"`), so a sectioned run's merge, a recompile and the
     variant strip all rebuild the same plan. Recompiling is idempotent.
4. **The AI tab** sends the plan prompt and asks for the whole plan in one
   reply (`ai/layoutEngine` = `compile`, the default; `polish` restores the
   old path). The variant strip offers the runner-up layout families via
   `compile_candidates`. In `auto` mode, a geometry reply still goes
   through polish.

## Kit faces that fit any size

These were fixed in hmi-ui (C) and the QML kit alike:
- ShClusterGauge: the caption is fitted to the chord inside the ring of
  scale numbers, and long scale numbers ("10000") use a smaller face.
- ShGearIndicator: a row wider than its box is measured again with the
  glyphs scaled to fit.
- ShAutoReadout: a value wider than its slot first takes the icon's place,
  then a smaller face (no less than 0.3 h), instead of being cut off.
- ShEngineBar: the label is held to the bar's width; it shrinks, then
  ends in an ellipsis.

## How it was tested

- **Live:** the lab model (through opencode) on six briefs, four of them
  held out from tuning (water dosing, CNC, plus re-runs). Every reply was
  compiled and rendered by hmi-ui and checked by eye. A gallery is above.
- **The real Studio:** MainWindow on the desktop, AI Design tab, brief sent,
  reply streamed, compiled, auto-applied to the Designer canvas. This run
  surfaced the "section 1" request conflict, a duplicate-key title loss, and
  a re-entrancy bug that marked successful turns "Cancelled" (the panel
  preview's nested event loop delivered the worker's `finished` mid-turn).
  All three are fixed.
- `tests/test_layout_compiler.py`: 22 tests. The existing AI and layout
  suites (269 tests) pass, and hmi-ui ctest passes 14/14 on Linux.

## Roadmap: what would make it better still

1. **Designer "Tidy up" through the compiler.** Done for pages the
   compiler built (0.1.3); hand-drawn pages are still polished. Offer "Compile layout", which uses `infer_sections`
   and keeps `_section` marks, plus a section/role editor in the Layers
   panel so a designer can regroup cards and recompile.
2. **Size constraints in the Properties panel.** Done in 0.1.3 as **Size
   on screen** on the Design tab; a per-page density override is still to
   come. Originally: expose `_size`
   (compact/normal/large) and a per-page density override, so a designer can
   pin a card's prominence without editing JSON.
3. **Critic aligned with the compiler.** Add pixel checks for text past a
   widget's box (the clipping axis exists; feed it per-widget bounds) and
   score the compiled variants with the hmi-ui render, not geometry alone.
4. **Plan validation round-trip.** When intake had to repair heavily or a
   section came back empty, ask the model once for a corrected plan, sending
   it the validator's notes rather than retrying blind.
5. **Multi-page plans.** Navigation strips and a per-system detail-page
   template, compiled with the same tokens so pages look like one product.
6. **Light theme and brand tokens.** The compiler takes every colour from
   Theme tokens already; add a brief-driven accent and verify contrast with
   the critic's contrast axis.

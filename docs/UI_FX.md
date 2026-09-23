# UI effects: Libraries.dev ported to QPainter

Status: design frozen 2026-09-23 (branch `feat/ui-fx`).

[Libraries.dev](https://github.com/Jakubantalik/Libraries.dev) (MIT, (c) 2026
Jakub Antalik) is a set of React effects for AI-agent interfaces. The Studio
is PySide6, so nothing can be dropped in; each effect is re-implemented in
`ui/python/fx/` with QPainter, keeping the original's tuned numbers.

## Constraints

* **Pure QPainter.** No numpy (the packaged Studio's spec excludes it), no
  OpenGL, no QtWebEngine. Per-pixel work in Python is too slow at 60 fps, so
  shader and SVG-filter effects are rebuilt from gradients, paths and
  composition modes.
* **One clock.** `fx.FxClock` is the only timer; effects subscribe while they
  animate. Nothing ticks when nothing moves; a hidden widget costs nothing.
* **An off switch.** `fx.set_animations_enabled(False)` (the Studio's
  "Animations" toggle, QSettings `ui/animations`) freezes every effect on a
  still frame that still reads well.
* **Time enters only as `t`.** `paint_frame(painter, t)` / `advance(t, dt)`
  never read the clock themselves, so tests drive frames deterministically
  with `widget._tick(t)`.
* **Both themes**, from `ui.python.shadcn.color(...)` tokens where the
  Studio has them, else the originals' dark / light values.

## Effects and where they go

| Module | Original | Studio placement | Port notes |
|---|---|---|---|
| `liquid.LiquidTabBar` | liquid-gooey `effect="move"` (Tabs demo) | the primary navigation (Designer, AI Design, Code, ...) | geometric goo: spring pill + tail droplets + necks (no blur/threshold) |
| `beam.BorderBeam` | border-beam `sm` / `md` / `line` | AI Design prompt card and the agent composer while a model works; Connect while connecting; the deploy card while deploying | conic masks with QConicalGradient; CSS filters applied to stop colours; blur by downscaled layer |
| `orb.ThinkingOrb` | thinking-orbs (9 states) | AI Design's run orb (thinking / streaming / parsing), the agent panel's reasoning header | exact: the engine is pure maths drawing circles |
| `avatar.BotAvatar` | bot-avatars | the agent panel header: `working` while busy, `sleeping` when stopped / failed, `default` idle | "smooth"/"crisp" shading (slices + overlays), not "plastic" |
| `metal.MetalRing` / `paint_metal` | metal-fx (liquidMetal) | the Studio logo in the top bar | gradient stripes + RGB dispersion + dome highlight |
| `mosaic.MosaicView` | img-fx `sweep-gradient` | the Code section's preview pane, widget-picker thumbnails while hmi-ui renders | per-cell fillRect at 15 fps, cell-stepped reveal |
| `glow.WorkingGlow` | voice-glow `processing` mode | a sweep under the agent header / AI Design card while busy | offset radial lobes, no audio |

Pulse-type border beams, the metal glow hotspot / pointer bend, the
thinking-orbs cursor gravity and the bot-avatar whirl are out of scope.

## Reading the originals

The clone lives at
`C:\Users\hithe\AppData\Local\Temp\claude\C--Users-hithe-Documents-MIL-HMI-PROJ-EmbeddedDisplay\50189602-8224-4b64-8c4e-1f2bd61ecba0\scratchpad\libdev`
(`packages/<name>/src`). Useful shortcuts:

* border-beam: `spec/beam-spec.json` has every tuned number (colorful, mono,
  ocean, sunset); `styles.ts` for the layer construction; conic stops map to
  Qt as `QConicalGradient(centre, 90 - fromAngle)` with stop `1 - p`.
  Filters: `ports/react-native/border-beam-native/src/colorMatrix.ts`.
* thinking-orbs: `src/engine/*.ts` is pure maths; `profiles.ts` /
  `presets.ts` hold the per-size tuning (`spec/orbs-spec.json` too).
* bot-avatars: `src/draw.ts`, `engine.ts`, `shapes.ts` (+
  `scripts/gen-shapes.mjs`), `color.ts`; the React Native Skia port in
  `ports/react-native` maps nearly 1:1 onto QGradient.
* metal-fx: the shader is in `ports/ios/MetalFxKit/Sources/MetalFxKit/MetalFxShaders.metal`;
  presets in `src/engine/presets.ts`.
* img-fx: `src/engine/shaders.ts` (sweep-gradient field, cell look),
  `src/engine/reveal.ts` (reveal), `src/presets/*`.
* liquid-gooey: `src/observer.ts` (springs, tail), `LiquidItem.tsx`,
  `sites/gooey/playground/demos/Tabs.tsx` + `styles.css` (the tab demo).
* voice-glow: `src/presets.ts` (processing), `src/styles.ts` (colours),
  `src/voiceDriver.ts`.

## Gates

`tests/test_fx_core.py` (shared), `test_fx_beam.py` (beam + glow),
`test_fx_orb.py`, `test_fx_avatar.py`, `test_fx_metal_mosaic.py`,
`test_fx_liquid.py`. Visual check: `python tools/fx_gallery.py out.png`
renders every effect, both themes, at four moments.

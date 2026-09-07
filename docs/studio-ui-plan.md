# Studio UI implementation and improvement plan

## Outcome and evidence

The Studio now treats its widget library as a visual authoring surface rather than a plain type list, and the nine industrial widgets added in this cycle participate in the same registry, inspector, generator, preview, and runtime paths as the existing controls. The baseline catalog contained 36 registered widgets and attempted every widget in both themes. Eight new controls failed in both themes because of concrete QML errors: invalid signal handlers in `ShSlider`, conflicting generated signals in `ShToggle`, `ShCheckbox`, and `ShNumInput`, unavailable popup/scroll types in `ShSelect` and `ShAlarmTable`, an invalid alignment property in `ShNumDisplay`, and invalid syntax in `ShAnalogDisplay`.

The implementation preserves the fixed aviation palette. EFIS sky, ground, caution, warning, navigation, and aircraft colors remain independent from the Studio light/dark mode because they communicate operational meaning. No panel deployment is part of this work.

## Implemented phases

### 1. Runtime controls and theme parity

The broken industrial QML controls were replaced with responsive, self-contained Qt Quick components. Slider, toggle, and checkbox support keyboard focus and activation. Numeric input supports direct editing, validation, Up/Down adjustment, and bounded increment/decrement buttons. Select uses a real Qt Quick Controls popup and accepts its option list from the generated model. Numeric display and analog display use bounded text and valid geometry; analog display supports both horizontal and vertical layouts and always shows the actual value. Alarm and trend components expose honest empty states instead of fabricated operational data.

Dark surfaces now use a subtle `#303036` border in both `tokens.json` and the QML singleton. The light token is unchanged. QML font selection resolves one installed family at runtime, preferring Inter, Noto Sans, DejaVu Sans, Segoe UI, and Arial, then falling back to the application font. This avoids passing a comma-separated CSS stack as one nonexistent QML family.

### 2. Registry, inspector, and generation

The registry defines appropriate initial sizes for the new controls so newly inserted widgets are usable without immediate resizing. Select exposes a comma-separated `options` string in the property inspector. The generator trims that string, omits empty entries, and emits a QML string-array model. Toggle continues to save the established `onLabel` and `offLabel` project keys but generates the valid runtime properties `onText` and `offText`, preserving existing project compatibility. Analog exposes `vertical`, while trend data and alarm arrays remain binding targets instead of unsafe free-form JSON editor fields.

Property editing keeps typed numeric controls for normal values and falls back to text only when an existing project contains an expression that cannot be parsed as a number. Existing project properties are not discarded during generation.

### 3. Widget-library workflow

The left-hand palette is searchable by display name, QML type, and category. It shows per-category and total result counts, an explicit empty state, theme-aware thumbnails, and persisted favorites. Authors can insert by drag, double-click, or Enter. Favorites are available through the context menu or Ctrl+F while the palette has focus. Ctrl+L focuses search only within the widget-library subtree, avoiding an application-wide shortcut collision.

Thumbnail rendering uses each widget's registered size, scales large widgets down without inflating small controls, and saves/restores both painter state and the global preview theme. This prevents one thumbnail painter or theme switch from contaminating later thumbnails or the canvas.

### 4. Preview and runtime consistency

Canvas painters cover every registered component and read color palettes from the shared token file. The new painters reflect the same control state as runtime: slider value, toggle/checkbox state, numeric value, select placeholder/options, analog orientation, and alarm/trend empty states. The annunciator caption remains visible when unlit, preserving a crucial avionics affordance.

`ui.widget_catalog` provides the repeatable visual gate. By default it renders untouched registry defaults for every widget in dark and light themes. `--samples` adds illustrative values for visual review without changing registry defaults. The tool writes individual images, category sheets, and a JSON report, keeps native-size captures from being enlarged, and treats runtime warnings as failures except font availability noise and the known intentional `data` override used by the trend component.

## Acceptance criteria

| Area | Required behavior | Validation |
| --- | --- | --- |
| QML availability | Every registered widget instantiates in light and dark modes | 72 catalog renders, zero component errors |
| Theme parity | Dark borders are visible and Python/QML token values agree | token parity tests and catalog review |
| Select | Inspector options generate a trimmed QML model and popup selection updates `currentIndex` | generator test plus sample catalog |
| Compatibility | Saved toggle `onLabel`/`offLabel` become runtime `onText`/`offText` | generated QML assertion |
| Numeric input | Direct text entry and keyboard/button adjustment remain bounded | runtime interaction QA |
| Analog | Horizontal and vertical modes show the actual value | default and sample catalog review |
| Empty data | Trend and alarm controls clearly state that no data is present | default catalog review |
| Palette | Search, counts, favorites, drag, double-click, and Enter work | focused Studio UI tests and manual smoke |
| Aviation | Fixed EFIS conventions do not follow UI theme | preview regression tests |

## Validation and rollout

Validation proceeds from cheap checks to broad checks: Python compilation and whitespace validation; focused generator, model, preview, palette, and toolbar tests; the 72-render default catalog; the 72-render sample catalog; then the complete test runner. Finally the Studio is launched from the repository entry point and its log is checked for startup exceptions. A failure at any earlier gate is fixed before moving to the next.

Rollout should keep this work as one reviewable Studio/UI change set. Generated CI fixture updates belong with generator changes so golden output remains intentional. Temporary catalogs and logs are review artifacts and should not be shipped. Panel deployment stays a separate, explicitly authorized step.

## Deferred improvements

- Undoable multi-widget templates require a command-model design that covers creation, nesting, and assets; they should follow stabilization of the individual insertion path.
- Binding diagnostics need a clear model for missing, stale, and circular data rather than a generic warning badge.
- Alignment guides and snapping deserve a dedicated interaction pass because they affect drag precision and undo behavior.

These are valuable next steps, but none should delay making every current widget compilable, discoverable, and accurately previewed.

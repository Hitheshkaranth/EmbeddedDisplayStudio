# Reference image workflow

In AI Design, attach or paste the reference, select the panel resolution, and
send the request. Image uploads now use the OCR-grounded pipeline; ordinary text
requests retain the existing layout engine. Windows OCR language support,
Pillow, NumPy, an image-capable model, and the host native renderer are required.

## Current automatic upload path

1. The first image is prepared once, with a conservative device-bezel crop.
2. Windows OCR measures text and word boxes using full-image and overlapping
   tile passes. Spatial gaps separate unrelated columns and caption/readout pairs.
3. Detected text pixels are removed from a source-derived decorative backing.
   Native editable text is reconstructed using measured positions, foreground
   colors and Inter font metrics. Equipment and chart artwork remains raster.
4. The model classifies OCR IDs as labels, readings or controls. It cannot move
   text, omit IDs, or invent screen geometry. An invalid classification gets
   one complete retry; failure is reported instead of falling back to a generic UI.
5. The deterministic compiler creates editable widgets and simulated tags.
   Unknown controls are disabled; missing pages and PLC addresses are not invented.
6. The host native runtime renders the candidate. The generated preview appears
   inside AI Designer without deploying to the panel. **Apply** loads it into the
   workspace. Failed checks prevent automatic preview/publication of that candidate.

Each run saves `source.png`, `ocr.json`, model classifications, `project.edsui`,
`simulation-defaults.json`, the artwork/removal mask, `native-preview.png`, and
`reference-acceptance.json`. Reports separate detected-text reconstruction from
visual fidelity, runtime behavior and deployment. No manual layout corrections
are included in automatic trial results.

The independent `render-text-check.json` compares a second OCR pass of the
native render against source text. It is a review diagnostic: small text can
produce false mismatches. AI Designer shows a warning when it disagrees.
Simulation checks separately verify source sample values and changing numeric
signals. These do not certify a physical device or real equipment connection.

For a reproducible run using the same pipeline without deploying:

```powershell
python -m tools.hmi_deployer.reference_benchmark image.png --output .tmp/fresh-image-trial --base-url http://your-model-server:8080 --model your-vision-model
```

Use a new output directory for every run. If needed, place the API key in
`HMI_AI_API_KEY`; credentials are not written into the evidence.

OCR can misread characters and miss text; cleanup can leave marks. The font is
an approximation, and raster artwork is not an editable vector diagram. Passing
configuration/coverage checks does not establish complete image understanding or
pixel-identical output. Review the native render and exercise simulated controls.

### Trial evidence, 23 October 2026

Live model trials are under `.tmp/grounded-trials/20261023-171720`.
The raw replies are preserved. The kiln live trial failed because the model
classified timestamps as numeric readings; an earlier simulation check also
sampled a point where low-precision readings rounded back to their source value.
The general fixes classify timestamps as static and test a visible waveform peak.

Replaying those unedited model responses through the corrected pipeline produced:

| Reference | Native OCR text elements | Simulated tags | Reconstruction/configuration/simulation checks |
| --- | ---: | ---: | --- |
| ChemVista | 158 | 29 | Pass |
| Cement kiln | 179 | 39 | Pass |

The `chemvista-regression` and `kiln-regression` subdirectories explicitly record
`model_response_replay: true`. These are regression replays, not fresh successful
model calls. No screenshot-specific coordinates or manual project edits were used.
Both independent rendered-text checks require review. Some source text is
misrecognized, behavior inference is incomplete, and charts/equipment remain raster
artwork. These results do not establish reliable exact conversion or deployment.

## Earlier model-positioned implementation

The following describes the earlier measured-plan path, retained for existing
plans and tests. It is no longer the default image-upload generation path.

## Implementation

1. `reference_workflow.prepare_reference_images` conservatively removes a dark
   device bezel around a light application. It never modifies the supplied file.
   The prepared attachment is shared by generation, asset crops, and review.
2. `REFERENCE_PLAN_SCHEMA` requires the application theme, source dimensions,
   viewport, section boxes, and individual widget boxes. The model must identify
   widgets and behavior; a valid JSON response alone is not acceptance.
3. The compiler preserves source positions using uniform aspect fit. It does not
   insert cards, change labels, or rearrange a measured page. Source font/icon
   metrics are stored so recompiling or changing panel size does not scale twice.
4. Palette extraction excludes the bezel and supports light screens. The native,
   QML, and canvas renderers support an optional `ShDataField.valueColor`, so live
   readings can remain legible on light backgrounds.
5. The reference audit identifies missing geometry, bindings, actions, invalid
   destinations, out-of-bounds elements, and whole-screenshot substitution. The
   tab makes at most one configuration retry and keeps unresolved issues visible.
6. Visual review receives the reference and native render, plus source boxes. It
   can correct measured boxes, artwork crops, and declared properties while
   retaining bindings/actions. Contained artwork and readout overlays are not
   automatically treated as collisions. A response with no fixes is not a pass.

All boxes address the same first attachment. The normal unit is 0–1000;
consistent percentage output can be normalized only with sufficient evidence,
and the inference is persisted for review. The viewport has its own fixed
0–1000 coordinate system. Supporting attachments do not change the crop source.

## Acceptance

`reference-audit.json` reports configuration readiness separately from visual
match, runtime operation, and deployment. Estimated text fit is a warning, not a
pixel comparison. Static artwork is explicitly identified. No similarity
percentage is invented.

Inspect the native render against the prepared reference, exercise bindings and
actions in Tag Lab, then verify the actual tag source on the target hardware.
A screenshot cannot establish equipment behavior, PLC addresses, alarm rules,
or missing pages. Different panel aspect ratios may require unused space or an
intentional redesign; uniform fitting cannot fill both shapes identically.

The ChemVista benchmark artifacts under `apps/chemvista-measured-test` and
`apps/chemvista-prepared-test` include model replies, native previews, validation,
and audit reports. These are diagnostic builds, not a deployment or an accepted
exact reproduction. The live trials exposed geometry-unit mistakes, incorrect
artwork selection, and missing behavior that the workflow reports for correction.

The separate `apps/chemvista-live-demo` was deliberately laid out and corrected
by the agents using the reference, then deployed to the bench panel. It has live
simulation readings and writable demo controls, with decorative equipment
artwork behind editable overlays. It is not the unmodified output of attaching
an image to AI Designer and pressing Generate, and does not establish automatic
image-to-deployment success. Deployment and live-feed evidence is recorded in
`.tmp/chemvista-live-acceptance`.

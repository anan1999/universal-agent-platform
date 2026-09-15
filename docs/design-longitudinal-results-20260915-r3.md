# Three-track longitudinal design benchmark

Each domain is an independent three-round project. Baseline and UAP begin every round from the same accepted checkpoint. Provider sessions are fresh; only UAP retains its project intelligence. Token claims require exact measured usage and both artifacts to pass the same cumulative deterministic contract.

| Track | Round | Problem | Baseline tokens | UAP tokens | Reduction | Baseline quality | UAP quality | Valid |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| ui-ux | 1 | Create the responsive and accessible medication-planner prototype described by the local brief and requirements. | 93434 | 90771 | 2.85% | PASS | PASS | True |
| ui-ux | 2 | Extend the existing prototype with a medication status filter, a visible conflict alert, and an aria-live status region. Preserve the established design tokens and responsive layout. | 96968 | 115387 | -18.99% | PASS | PASS | True |
| ui-ux | 3 | Add an accessible Add medication dialog to the existing prototype, including labelled fields, Escape-key close behavior, focus return, and reduced-motion support. Preserve prior behavior. | 102071 | 119813 | -17.38% | PASS | PASS | True |
| graphic-design | 1 | Create the standalone vector event poster described by the local assignment and poster brief. | 87479 | 88218 | -0.84% | FAIL | PASS | False |
| graphic-design | 2 | Extend the existing poster with a sponsor strip labelled exactly SUPPORTED BY HARBOR LAB. Keep the approved palette, hierarchy, and original layers intact. | 87248 | 104566 | -19.85% | PASS | FAIL | False |
| graphic-design | 3 | Create a companion square social.svg adaptation with viewBox 0 0 1080 1080. Reuse the poster palette and include the exact event, date, and venue copy with accessible title and description. | 91806 | 92608 | -0.87% | PASS | PASS | True |
| three-d-design | 1 | Create the valid Wavefront information kiosk described by the local assignment and model brief. | 87430 | 88344 | -1.05% | PASS | PASS | True |
| three-d-design | 2 | Extend the kiosk with a distinct keypad group using a new AccentMetal material. Preserve the existing model bounds, groups, and material assignments. | 69095 | 32718 | 52.65% | PASS | FAIL | False |
| three-d-design | 3 | Extend the kiosk with a canopy group using a new Canopy material while preserving all earlier geometry and the exact model bounds. Keep every face index valid. | 88085 | 106404 | -20.80% | PASS | FAIL | False |

## Aggregate

- Valid paired rounds: 5/9
- Baseline tokens: 471709
- UAP tokens: 506923
- Token reduction: -7.47%
- Quality equivalent: False
- Savings claimable: False

### ui-ux

- Valid rounds: 3/3
- Baseline / UAP: 292473 / 325971 tokens
- Reduction: -11.45%

### graphic-design

- Valid rounds: 1/3
- Baseline / UAP: 91806 / 92608 tokens
- Reduction: -0.87%

### three-d-design

- Valid rounds: 1/3
- Baseline / UAP: 87430 / 88344 tokens
- Reduction: -1.05%

## Interpretation limits

The quality gate verifies brief compliance, file validity, cumulative feature retention, accessibility structure, palette/typographic constraints, and 3D geometry integrity. It does not replace blind human evaluation of aesthetic preference. Provider token counts also do not map one-to-one to subscription quota units.

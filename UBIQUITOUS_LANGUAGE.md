# Ubiquitous Language

## Baseplate geometry

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Baseplate** | The generated part composed of standard grid cells plus optional fillers and feature cuts. | Plate, model |
| **Core Cell** | A nominal 42 mm grid cell used as the primary repeated unit in a baseplate. | Normal cell |
| **Filler Cell** | A side or corner cell with custom width/height used to extend baseplate footprint. | Strip cell, border cell |
| **Tiny Cell** | A cell that did not have enough room for bin-base geometry and therefore has an empty bin-base cutout. | Empty cell, null cell |
| **Baseplate Layout** | The occupancy matrix used for final baseplate operations, including fillers when enabled. | Expanded layout, layout |
| **Core Baseplate Layout** | The pre-filler layout containing only core-cell occupancy. | Base layout |

## Profile and dimensional terms

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Apex** | The top reference level of the base profile equal to `BaseProfileMainHeight + BaseProfileMainHalfWidth`. | Base top |
| **Main Profile Half Width** | Half-width of the vertical base profile section (default 2.15 mm). | Main half, half width |
| **Main Profile Height** | Height of the vertical base profile section (default 2.5 mm). | Main height |
| **Top Chamfer** | The 45 degree top chamfer of the base profile. | Upper bevel |
| **Lower Chamfer** | Optional lower chamfer of the base profile (default size 0.7 mm when enabled). | Bottom chamfer |
| **Bin Outer Radius** | Outer fillet radius driving many profile and wall-thickness calculations (default 4 mm). | Outer radius |

## Feature operations

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Click Springs** | Snap feature geometry (positive/negative spring/notch forms) added to eligible cell sides. | Snap springs |
| **Clip Cutouts** | Connector cutouts created at eligible neighboring-cell boundaries. | Connecting clips, clips |
| **Junction Screw Holes** | Through-hole and counterbore feature at eligible 2x2 cell intersections. | Screw holes, junction holes |
| **Cell-level Operation** | Geometry operation applied to a single cell prototype before replication/copy placement. | Per-cell step |
| **Plate-level Operation** | Geometry operation applied after cells are assembled into the full baseplate shape. | Global step, final-stage step |

## Validation and tests

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Body Volume Test** | Regression test that locks exact resulting body volume for a fixed scenario. | Locked volume test |
| **Bounding Box Test** | Regression test that locks exact X/Y/Z extents for a fixed scenario. | BBox lock |
| **Volume Delta Test** | Test that compares volume difference between two controlled scenarios. | Relative volume check |
| **Defaults-first Test Setup** | Test convention to keep feature defaults unless a specific override is requested. | Ad-hoc toggles |

## Relationships

- A **Baseplate** is assembled from **Standard Cells** and optional **Filler Cells**.
- **Initial Baseplate Layout** is transformed into **Baseplate Layout** when fillers are incorporated.
- **Baseplate Tiny Layout** is index-aligned to **Baseplate Layout**.
- **Tiny Cell** status is determined per cell and used as a filter in feature eligibility.
- **Clip Cutouts** and **Junction Screw Holes** use neighbor-based candidate detection on **Baseplate Layout**, then skip candidates involving any tiny participant.
- **Cell-level Operations** build per-cell geometry; **Plate-level Operations** modify assembled baseplate geometry.
- **Body Volume Test** and **Bounding Box Test** lock reference geometry outputs.

## Example dialogue

> **Dev:** "For this right-side filler case, should neighbor checks use only standard cells?"
> **Domain expert:** "Use **Baseplate Layout** for candidate detection, because fillers are part of the plate geometry."

> **Dev:** "And if one participating cell is tiny?"
> **Domain expert:** "Skip that candidate. A **Tiny Cell** means there was not enough room for bin-base geometry."

> **Dev:** "So layout naming should be explicit?"
> **Domain expert:** "Yes: **Initial Baseplate Layout** before fillers, **Baseplate Layout** after fillers, plus **Baseplate Tiny Layout** for tiny flags."

> **Dev:** "For regression, we lock both dimensions and volume?"
> **Domain expert:** "Correct - use **Bounding Box Test** and **Body Volume Test** separately."

## Flagged ambiguities

- "layout" is too vague; use **Initial Baseplate Layout** or **Baseplate Layout** explicitly.
- "core cell" and "standard cell" referred to the same concept; use **Standard Cell**.
- "expanded layout" and "baseplate layout" referred to the same concept; use **Baseplate Layout**.
- "structural cell" was introduced but not desired; use **non-tiny cell** wording instead.
- "top crop + margin" was discussed as behavior, but domain intent is that top crop height itself is fixed by parameter and margin should not redefine that semantic.

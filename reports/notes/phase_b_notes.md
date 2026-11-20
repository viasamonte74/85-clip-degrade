## Notes (hand-written)

### Sources added in Phase B
- **SVT Open Content Video Test Suite 2022 (CC BY 4.0)** — six real-camera locations (forest lake, midnight sun,
  smithy, smoke sauna, water flyover, waterfall) shot on a Blackmagic URSA at 3840x2160 50p, published as lossless
  JPEG 2000 Rec. 709 QuickTime masters (25-66 GB each). Only the needed samples are fetched: the moov sample table
  is read with FTP REST ranges, each JP2 sample is stored byte for byte (decodes identically to the publisher's MOV,
  verified). References keep every 2nd source frame (50 -> 25 fps; no interpolation; recorded as a transform step).
  The synthetic "SVT Video Quality Test" and the HDR-only "fireside" are not used.
- **Elephants Dream (CC BY 2.5)** — original 1080p PNG frames; licence evidence: the project site's statement about
  the HD frames hosted by Xiph, and the film's own end-credit frame (read visually; image hash recorded).
- **Netflix Chimera (CC BY 4.0, aom_test_materials tree)** — same mirror-contradiction treatment as Meridian.
- **Sol Levante (Netflix, CC BY 4.0)** — 2D animation, placed in the rendered/animation category's cartoon and
  particles subcategories and flagged as not 3D-rendered.
- **Wikimedia Commons** — reviewed file by file (see below).
- **Procedural Blender scenes** (CC0, this project): nine new scene types; Cycles 12 spp with OptiX denoising or
  EEVEE (about 60/40 by frames), chosen per clip.
- **Screen layouts** (CC0, this project): five new layouts (notebook, htop-like monitor, monitoring wall, mail
  client, ledger) next to the pilot's five.

### Rejected or not used (new in Phase B)
- Blender Studio films as uploaded to Commons (Spring, Sprite Fright, Hero, Coffee Run, Wing It!, Caminandes):
  858-1080 lines at 1.2-3.8 Mbps — not clean 1080p masters. The studio's own pages offer no unauthenticated download.
- NRK railway recordings on the Xiph mirror: 1080p H.264 at ~3.7 Mbps and no licence file.
- Commons: watermarks/logos, archival or AI-upscaled film (e.g. a "4K 60 fps" 1906 film), satellite/graphics
  composites, files still in "License review needed", talking heads and identifiable people at sensitive events,
  cosplay of third-party characters, advertising-dominated scenes. Every decision and reason is recorded.

### Label corrections
Two Sintel windows showed different content than the proxy thumbnails suggested: `r3d_sintel_bamboo` is a cliff over
a city (architecture, not vegetation) and `r3d_sintel_market` is character animation (not fast motion). Labels were
corrected in the plan and synced to the metadata; the clip ids were kept.

### Splits
Groups are allocated once with the full plan. The film groups are large, so the automatic allocation put every film
in train; before any of its data existed, Sol Levante (3 clips) was moved to validation so an evaluation split
contains film content, and three not-yet-rendered procedural groups moved to train to keep 96/12/12.

### Shared machine
The container has a 23-CPU quota split by the owner between the Cooling solves (20) and the other sessions (3).
`nice` does not protect them under a container-wide quota, so from 2026-11-20 01:50Z every dataset process is pinned
to CPUs 2-3 (about 2 CPUs) and Blender keeps its VRAM under ~6 GB next to the LTX job (agreed with the other
sessions). This sets the Phase B throughput. Degradation therefore runs in two passes: first one x2 and one x4
variant per original (480 pairs), then the second variant per factor (960 pairs) — the recipes are fixed by seed, so
the order does not change any output.

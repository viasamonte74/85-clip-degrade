# Phase B report — toward 240 originals / 960 pairs (2026-11-20T02:36Z)

## Progress

| stage | clips |
|---|---|
| planned (pilot + Phase B) | 205 |
| reference prepared | 49 |
| 4 degraded variants | 26 (122 variants) |

## Coverage (planned; prepared in brackets)

| category | planned | prepared | target |
|---|---|---|---|
| 3d_rendered | 120 | 24 | 120 |
| screen | 60 | 14 | 60 |
| real_camera | 25 | 11 | 60 |

**3d_rendered**

| subcategory | clips | share | target |
|---|---|---|---|
| mechanical_rotating | 24 | 20.0 % | 24 |
| natural_environment | 23 | 19.2 % | 24 |
| architecture_signs_text | 19 | 15.8 % | 18 |
| cartoon_stylized | 19 | 15.8 % | 18 |
| reflective_particles_fluids | 18 | 15.0 % | 18 |
| fast_motion | 17 | 14.2 % | 18 |

**screen**

| subcategory | clips | share | target |
|---|---|---|---|
| code_editor | 15 | 25.0 % | 15 |
| spreadsheet | 15 | 25.0 % | 15 |
| dashboard_charts_tables | 12 | 20.0 % | 12 |
| documents_ui | 9 | 15.0 % | 9 |
| terminal_logs | 9 | 15.0 % | 9 |

**real_camera**

| subcategory | clips | share | target |
|---|---|---|---|
| people_hands_activity | 6 | 24.0 % | 12 |
| water_rain_reflections | 6 | 24.0 % | 12 |
| low_light_motion_blur | 5 | 20.0 % | 12 |
| animals_foliage_nature | 4 | 16.0 % | 12 |
| urban_vehicles | 4 | 16.0 % | 12 |

| orientation | clips | share |
|---|---|---|
| landscape | 166 | 81.0 % |
| portrait | 39 | 19.0 % |

| frame rate | clips | share |
|---|---|---|
| 30 | 63 | 30.7 % |
| 60 | 53 | 25.9 % |
| 24 | 47 | 22.9 % |
| 25 | 32 | 15.6 % |
| 60000/1001 | 7 | 3.4 % |
| 30000/1001 | 3 | 1.5 % |

| duration (prepared length where available) | clips | share |
|---|---|---|
| ~4 s (<5) | 101 | 49.3 % |
| 6-8 s (5-9) | 62 | 30.2 % |
| ~10 s (9-10) | 42 | 20.5 % |

| licence | clips | share |
|---|---|---|
| CC0-1.0 | 146 | 71.2 % |
| CC-BY-3.0 | 18 | 8.8 % |
| CC-BY-4.0 | 11 | 5.4 % |
| netflix_sdr_segments | 9 | 4.4 % |
| xiph_elephants_dream | 8 | 3.9 % |
| netflix_chimera_aom | 3 | 1.5 % |
| svt_open_content_2022 | 3 | 1.5 % |
| xiph_dweebs8k | 3 | 1.5 % |
| CC-BY-SA-4.0 | 2 | 1.0 % |
| netflix_elfuente | 2 | 1.0 % |

## Source diversity

| category | independent groups | largest groups |
|---|---|---|
| 3d_rendered | 91 | film_sintel (10), film_elephants_dream (8), film_big_buck_bunny (8), film_daily_dweebs (5), film_sol_levante (3) |
| screen | 60 | own_screen_terminal_s5033 (1), own_screen_terminal_s5032 (1), own_screen_terminal_s5031 (1), own_screen_terminal_s5030 (1), own_screen_terminal_s5029 (1) |
| real_camera | 11 | film_sparks (4), film_el_fuente (4), film_nocturne (3), film_meridian (3), film_chimera (3) |

## Splits (by clip, groups never cross splits)

| category | train | validation | test | unassigned |
|---|---|---|---|---|
| 3d_rendered | 96 | 12 | 12 | 0 |
| screen | 48 | 6 | 6 | 0 |
| real_camera | 19 | 3 | 3 | 0 |

## Wikimedia Commons review

Shortlisted files reviewed one by one: 8 recorded decisions ({'reject': 5, 'reserve': 3}). Rejections and reasons: `metadata/commons_review.jsonl`; all decisions: `config/commons_review.yaml`.

## Storage

| directory | GB |
|---|---|
| data/references | 15.3 |
| data/degraded | 0.1 |
| data/downloads | 54.7 |
| free | 201 |

Reference preparation: median 158 s per clip (n=49).

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


# sn85-dataset — licensed 1080p references and second-order degradation for `sn85-upscaling-006`

Data engineering only: no model training, no AI video generation, no miner submission.
The pipeline collects commercially trainable 1080p originals (3D renders, screen content,
real camera footage), normalises them into lossless references and makes low-resolution
inputs with a randomised two-stage degradation modelled on the practice-pack-006 recipe.

## What is public and what is assumed

`reports/official_source_audit.md` lists the competition identifiers used (manifest digest,
repository commits, practice-pack hashes), the published requirements and the recipe in
kind. **Every parameter range in `config/degradation.yaml` is an experimental assumption**
unless the comment says otherwise: VidAIO has not published per-item parameters or their
distributions, and this project does not claim to reproduce them. The ranges were checked
against the CC0 practice inputs p02-p08 only (`reports/degradation_analysis.md`); the
evaluation-only items p01, p09 and p10 were never downloaded.

## Layout

```
config/degradation.yaml     recipe distribution (versioned; v1.2 after CC0 calibration)
config/sources.yaml         licensed collections with asset-level evidence; rejected sources
config/pilot_clips.yaml     Phase A plan (24 originals)
src/sn85ds/                 library: media I/O, colour, degradation ops/recipes/pipeline,
                            acquisition (HTTP, remote zip, references), screen scenes,
                            Blender procedural scenes, validation, reports
tools/                      CLI steps (below)
data/downloads/<id>/        masters (frames / y4m ranges / renders) + manifest.json
data/references/<id>.mkv    immutable FFV1 references; hard links in data/references/<split>/
data/degraded/<split>/x2|x4 LR inputs (MP4, H.264 or HEVC)
data/practice/              CC0 practice items p02-p08 (verified against SHA256SUMS)
metadata/                   sources, licenses, references, variants (JSONL), splits.json,
                            candidates.jsonl, quarantine.jsonl, CSV summaries
reports/                    audits, dataset summary, degradation analysis, validation.json,
                            contact_sheets/
```

`data/`, `third_party/` and `logs/` are not meant for Git (large binaries).

## Setup

```sh
uv venv --python 3.12 .venv && . .venv/bin/activate
uv pip install -e '.[test,screen]'
python -m playwright install --with-deps chromium     # screen-content rendering
# Blender (procedural 3D scenes): tools fetch nothing themselves; install 4.5 LTS into third_party/
#   https://download.blender.org/release/Blender4.5/blender-4.5.9-linux-x64.tar.xz (sha256 in blender-4.5.9.sha256)
```

System: ffmpeg/ffprobe with libx264, libx265 and FFV1 (tested with 6.1.1). All heavy steps run at `nice 19`
with a bounded number of workers; this machine shares its CPU quota with other jobs.

## Steps

| step | command | output |
|---|---|---|
| 1 discover | `python tools/discover_sources.py` | `metadata/candidates.jsonl`, `reports/source_capacity.md` |
| 2 audit licences | `python tools/audit_licenses.py` | `metadata/licenses.jsonl` (re-fetches every evidence URL and checks the quote) |
| 3 download | `python tools/download_sources.py [--plan P] [--only ID..] [--dry-run]` | `data/downloads/<id>/` + manifest |
| 3b render 3D | `python tools/render_procedural.py [--plan P]` | Blender frames + manifest (GPU, OptiX) |
| 4 references | `python tools/prepare_references.py [--plan P] [--kinds ..]` | FFV1 references, `references.jsonl`, `sources.jsonl` (screen clips are rendered here) |
| 5 splits | `python tools/assign_splits.py --plan P` | `metadata/splits.json` (group-aware 80/10/10) |
| 6 degrade | `python tools/generate_degradations.py [--variants-per-factor 2] [--workers 2] [--dry-run]` | LR inputs, `variants.jsonl` |
| 7 validate | `python tools/validate_dataset.py [--quick]` | `reports/validation.json`, `metadata/quarantine.jsonl` |
| 8 report | `python tools/create_report.py` | summaries, analysis, licence audit, contact sheets, CSVs |
| calibration | `python tools/calibrate_against_practice.py --tag T` | local vs CC0 practice statistics |
| reproducibility | `python tools/verify_reproducibility.py` | regenerates sampled variants / rebuilds references, compares checksums |

`tools/run_pilot_loop.sh` chains 4-6 while masters are still arriving. Every step is resumable.

## Reproducibility

- Recipes come from stable seeds `sha256(source_id, factor, variant index, config version)`; the full recipe,
  the config digest and the exact encoder command are stored per variant.
- Degradation output is bit-exact across runs: encoders run with 1 thread (libx264 with 2 frame threads
  produced 3 different bitstreams in 6 identical runs under load); tested for libx264 and libx265 in
  `tests/test_pipeline_e2e.py`, and checked on real variants by `tools/verify_reproducibility.py`. Re-running `generate_degradations.py` after deleting an output reproduces it;
  the stored `output_sha256` and `pre_encode_planes_sha256` verify it.
- Frame rates are exact rationals in `references.jsonl` (e.g. `60000/1001`). Matroska stores 1 ms timestamps,
  so ffprobe reads such references back as an approximation (19001/317); frames and frame counts are
  unaffected, and the LR inputs (MP4) carry the exact rate.
- References store `planes_sha256` (sha256 over every decoded 8-bit plane) and the decode/encode commands.
  Disk-saving mode: a reference can be deleted and rebuilt from its master manifest (URLs + per-file sha256)
  with `prepare_references.py --only <id> --force`; the planes checksum must match (verified bit-exact for
  frame-sequence masters). Screen references are the exception: headless-Chromium re-renders matched 248-249 of
  250 frames bit for bit, the rest differed by +-1 code value in 55 pixels, so screen references are never
  deleted in disk-saving mode (they are small); the stored FFV1 file is the immutable reference. Masters can likewise be
  dropped and re-downloaded from the manifest.

## Pipeline details

**References.** Optional source crop (left eye of the stereo BBB frames) -> centre crop to 16:9 or 9:16 ->
one downscale with swscale `spline` (never an upscale: masters smaller than the target are rejected) ->
8-bit 4:2:0 BT.709 limited -> FFV1 v3/Matroska. YUV masters stay in Y'CbCr (no matrix conversion);
RGB masters (renders, PNG/TIFF) are treated as BT.709 R'G'B' and converted with the explicit matrix in
`sn85ds/colour.py`. Frame rates are taken from the master and never resampled; 60 fps material is native
(BBB 3D rework, Netflix titles, renders, screen captures).

**Degradation** (`sn85ds/degradation/`): per clip one recipe, applied frame by frame on float R'G'B':
stage 1 blur (none / isotropic / anisotropic rotated Gaussian / optional directional line) -> resize 1 to
an intermediate size between the LR size and 1.7x it (area, bilinear, bicubic, Lanczos-3, spline36, all
antialiased) -> sensor-like noise (Poisson-Gaussian in linear light, optional spatial, cross-channel and
AR(1) temporal correlation, stronger on dark clips) -> optional JPEG round trip; stage 2 mild blur ->
resize 2 to exactly W/f x H/f -> optional weak noise; final libx264/libx265 ABR+VBV at a web bitrate,
GOP = round(2 x fps) with scene-cut key frames, yuv420p, BT.709 limited tags, MP4.

**Splits.** Unit = source group (parent film, recording session, scene file / seed). Validation and test
first receive one group of every category with >= 3 groups, then groups go to the split minimising the
squared deviation from 80/10/10. Assignments never move once made.

**Validation.** Licence allow-list and evidence; reference integrity (file + decoded planes checksums),
geometry, frame rate, duration <= 10 s, colour tags, black/frozen frames, hard cuts; variant codec, LR
size, frame count and rate, colour tags, GOP, and pairing consistency (no temporal offset, no spatial
shift > 0.5 px, correlation with the reference, degradation visible but not implausible); split isolation
(groups, exact duplicates, dHash near-duplicates across splits).

## Phase B (expansion toward 240 originals)

Plan: `config/phase_b_clips.yaml` (pilot clips stay in `config/pilot_clips.yaml`). Results and
shortfalls: `reports/phase_b_report.md`. Additional source routes and tools:

| step | command | notes |
|---|---|---|
| previews | `python tools/preview_candidates.py` | one frame per candidate segment (BBB 3D scenes, Elephants Dream, Netflix) to pick windows by eye |
| SVT 2022 | `download_sources.py` kind `ftp_mov_j2k` | ranged FTP reads of single lossless JP2 samples from the 25-66 GB QuickTime masters (moov parsed in `sn85ds/acquisition/ftp.py`); 50p -> 25p by keeping every 2nd frame, recorded as a transform step |
| Commons search | `python tools/discover_commons.py` | CirrusSearch per real-camera subcategory, per-file licence metadata, automatic screen (licence, >= 2560 px, bitrate, categories) |
| Commons shortlist | `python tools/commons_sheets.py` | title/category exclusions, ranking, uploader cap, stills from the Commons thumbnail service for review |
| Commons review | edit `config/commons_review.yaml`, then `python tools/commons_select.py` | one decision per file with reasons; accepted files are downloaded (API SHA-1 verified), checked for frame rate, scan type, HDR and genuine 1080p detail, cut-detected, and a window inside one shot is planned (`commons_window`) |
| generated clips | `python tools/plan_generated.py` | procedural Blender and screen clips filling the subcategory / duration / orientation gaps |
| render 3D | `python tools/render_procedural.py --plan config/phase_b_clips.yaml --interleave --shard k/2` | two queues on one GPU; Cycles (12 spp, OptiX denoiser) or EEVEE per clip; resumable per frame |
| drivers | `tools/run_phase_b_prepare_loop.sh`, `tools/run_phase_b_degrade_loop.sh` | run side by side: preparation (`--drop-masters`, one pass at a time under a lock) and degradation (`assign_splits.py --existing-only` + missing variants; first one variant per factor for every original, then automatically the second, up to all 960 pairs; worker count from `logs/degrade_workers`, read at the start of each pass); screen clips: `prepare_references.py --kinds screen` |

- **Disk-saving mode** (`prepare_references.py --drop-masters`): after a reference is written, its decoded planes
  are re-checksummed; only then are the downloaded master files deleted. The manifest (URLs, per-file sha256, byte
  ranges / sample indices) stays, so the master can be re-fetched and the reference rebuilt bit-exactly.
  Blender PNG frames are dropped too once the reference is verified (the render manifest keeps per-frame sha256, arguments and the scene script hash; a re-render reproduces the content, the FFV1 reference is the immutable artefact). Screen clips render straight into their reference.
- **Shared CPU quota** (`tools/adaptive_affinity.py --pid <degrade loop pid>`): the box's jobs share one container CPU
  quota, so the degradation loop runs on its agreed CPUs and the watchdog adds idle CPUs one at a time only while
  the quota has room (no throttled periods), dropping back at the first sign of throttling, with growing back-off.
- **Splits while the plan grows**: `assign_splits.py --existing-only` links references of groups that already
  have a split (so their degradation can start) and assigns nothing new; new groups are allocated once, with
  the complete plan (`assign_splits.py --plan config/phase_b_clips.yaml`).
- **Wikimedia Commons**: each file is its own licence record (file-page `LicenseShortName`, author, SHA-1);
  accepted licences CC0 / public domain / CC BY / CC BY-SA (ported variants flagged). Requests are sequential,
  paced and honour `Retry-After`; the API and the media servers both rate-limit unidentified clients.
- **New procedural scenes** (`sn85ds/blender/procedural_scenes.py`): forest (hair grass, instanced leaves),
  terrain, machine, clock, interior, tunnel, chrome, particles (baked sparks / snow / confetti), toon (EEVEE cel
  shading with inverted-hull outlines). The render manifest records the scene script's sha256.
- **New screen layouts** (`sn85ds/screen/scenes.py`): notebook, sysmon (htop-like), multiples (monitoring
  wall), mail (three-pane client), ledger (conditional formatting, merged headers).

## Licences of the material

See `reports/license_audit.md` and `config/sources.yaml`. In short: Blender open movies via Xiph (CC BY 3.0;
Daily Dweebs CC BY-SA 4.0), Netflix Open Content fetched from Netflix's own bucket (CC BY 4.0; older Xiph
copies carry BY-NC-ND notices and are not used — flagged for human confirmation), and this project's own
procedural renders and screen recordings (CC0). Identifiable people (Netflix live action) are flagged for
personality-rights review before any redistribution. Credit every CC BY / BY-SA source in the miner's
`LICENSES.md` plus an attribution file, as VidAIO's rulings require.

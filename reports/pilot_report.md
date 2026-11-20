# Phase A pilot report — 24 originals, 96 input/reference pairs (2026-11-19)

## Result

| item | target | actual |
|---|---|---|
| originals | 24 (12 3D / 6 screen / 6 camera) | **24** (12 / 6 / 6) from **17** independent source groups |
| degraded inputs | 96 (48 x2 + 48 x4) | **96** (48 + 48) |
| validation (deep: full-decode checksums, pairing alignment) | all pass | **96/96 variants pass; 21/24 references pass, 3 warn** (near-static screen frames, expected); 16/24 sources pass, 8 warn (review flags below) |
| split leakage | none | **0** group leaks, **0** exact or near-duplicate pairs across splits |
| licence evidence re-verified live | all | **9/9** evidence quotes still present at their URLs (`metadata/licenses.jsonl`) |
| reproducibility | bit-exact | sampled variants regenerated **bit-exact** (H.264 + HEVC); references rebuilt from frame masters **bit-exact**; screen re-render near-exact (point 6) — `reports/data/reproducibility.json` |
| tests | pass | **25/25** (`pytest`) |

Splits (group-aware): train 18 / validation 3 / test 3 — every split holds every category
(3D 10/1/1, camera 4/1/1, screen 4/1/1). Orientation 19 landscape / 5 portrait (21 %).
Frame rates: 24 (5), 25 (2), 30 (5), 60 (9), 60000/1001 (3), all native. Durations: 14 at ~4 s,
7 at 6-8 s, 3 at ~10 s (target 12/7/5; Nocturne moved from the 10 s to the 8 s bucket when its fade-out was cut).
Difficulty draws: mild 36 / medium 38 / heavy 22 (37.5 / 39.6 / 22.9 %; target 35 / 45 / 20).
Codecs: H.264 59 / HEVC 37. All five resize filters used in both stages.

## Problems found during the pilot and how they were fixed

1. **x264 bitstreams were not reproducible with 2 threads** (ABR + VBV): 3 different outputs in 6 identical
   runs under load. Encoder threads set to 1 (config 1.2.1, same recipes and seeds); all 96 variants were
   re-encoded; bit-exactness is now a test (x264 and x265).
2. **Two real-camera windows contained fades**: Sparks segment 30-511 starts with a ~260-frame fade-in from
   black (window moved to members 240-479); Nocturne segment 17140-17709 fades out from ~frame 490 (trimmed to
   480 frames). Caught by the black-frame check and per-frame luma.
3. **Matroska timestamps are 1 ms**: 60000/1001 references read back as 19001/317. Frames are unaffected; the
   exact rational rate is stored in `references.jsonl` and checked against the container within 1e-4.
4. **Validator false positives**, each confirmed with data before changing the check: temporal offset on
   near-static shots (now judged against the reference's own inter-frame change, plus a global offset test);
   phase correlation on dark, flat frames (peak response threshold); dHash near-duplicates between two dark
   frames (flat frames skipped); "different scene" on heavily blurred dense text (low-pass correlation).
5. **Download robustness**: blender.org answered HTTP 429 and once ignored byte ranges (returned the whole
   file); ranged reads now require 206, honour Retry-After, and fall back to one sequential stream.
   media.xiph.org served ~1 KB/s, so frames come from the Xiph AWS Open Data mirror (same files).
6. **Screen re-renders are near-exact, not bit-exact**: re-rendering the dashboard clip reproduced 248-249/250
   frames bit for bit (two runs); 1-2 frames differed by +-1 code value in 55 pixels (headless Chromium rasterisation).
   Stored screen references are therefore kept as the immutable artefact (never dropped in disk-saving mode).
7. **Licence mirror contradiction**: Xiph copies of Meridian and of the Chimera/El Fuente sequences carry
   CC BY-NC-ND notices. Only Netflix's own bucket copies (CC BY 4.0 file in the same tree) are used.

## Degradation vs practice (CC0 p02-p08 only)

Medians match at <= 30 fps (bitrate, PSNR vs area-downscaled reference, effective blur at x2, noise,
temporal residual); x4 local inputs are somewhat sharper than the three x4 practice items (HF ratio 0.59 vs
0.30). Details: `reports/degradation_analysis.md`. Calibration history: v1 -> v1.1 (bitrates shifted down:
all CC0 inputs sit in the lower ~40 % of the published ranges) -> v1.2 (x2 noise down, stage-1 blur up).

## Storage and throughput (this machine: CPU quota 23 shared with 20 busy cooling solver processes; GPU shared with an LTX generation job)

- masters 46.2 GB (BBB 3D 4K60 PNG frames are 13-26 MB each), FFV1 references 3.8 GB, LR inputs 80 MB.
- downloads ~10-12 MB/s (Xiph AWS mirror, Netflix S3 with 6 ranged connections).
- reference preparation median 75 s; Blender procedural renders 4-8 s/frame on the shared A6000;
  screen renders 0.6-1.4 s/frame (headless Chromium, 1080p PNG capture).
- degradation: 96 variants in 53 min wall (3 workers x 4 variants per decode pass, nice 19).
- Phase B estimate (960 variants): ~9 h of degradation at this contention, plus downloads and renders.

## Flags for human review (not blockers for local training)

- Netflix titles (Sparks, Meridian, Nocturne, El Fuente): identifiable people -> personality/privacy review
  before any redistribution; mirror licence contradiction (point 6) -> confirm the CC BY 4.0 reading.
- Daily Dweebs: CC BY-SA 4.0 -> derived clips stay BY-SA if distributed; attribution file required.
- Daily Dweebs frame rate 24 fps is inferred (1440 frames, 1-minute film), not stated by the publisher.

## Blockers and assumptions before Phase B (240 originals)

- **Real-camera diversity**: the verified real-camera collections come from 5 Netflix parent films; 60
  diverse originals need more independent sources. Surveyed route: Wikimedia Commons with per-file licences
  (379 allow-listed >= 1080p videos in 8 queries, many 4K at 100+ Mbps) — each file still needs privacy and
  third-party-content review (`config/sources.yaml` candidate_collections).
- **3D film diversity**: 4 parent films with downloadable licensed masters (BBB, Sintel, Daily Dweebs;
  Sol Levante is 2D and flagged). Group-aware splitting keeps each film in one split, so validation/test 3D
  will lean on independent procedural renders (one group per seed) unless more films are found.
  Elephants Dream (CC BY 2.5) is deferred only because media.xiph.org was throttled.
- **Storage**: ~270 GB free; 4K60 PNG masters dominate. Phase B should use disk-saving mode (delete masters
  after the reference is verified; manifests keep URLs + per-file sha256 for rebuilds).
- **Persistence**: /workspace on this instance is not a persistent volume — sync data off-box.
- All degradation parameters remain experimental assumptions (`config/degradation.yaml`).

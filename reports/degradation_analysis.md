# Degradation analysis: local variants vs CC0 practice-pack-006 inputs

Same statistics code for both (sn85ds/validation/degradation_stats.py). Practice items used: p02-p08 only (CC0); p01/p09/p10 are evaluation-only and were never downloaded. These numbers describe the degradation distribution; they are not the competition scorer.

| factor | metric | practice CC0 median [min, max] | local median [min, max] |
|---|---|---|---|
| x2 | bitrate_kbps | 1253.35 [914.20, 1706.10] | 1781.15 [855.00, 3869.10] |
| x2 | luma_psnr_vs_area_down | 33.73 [24.52, 39.95] | 35.62 [22.95, 49.84] |
| x2 | hf_energy_ratio | 0.21 [0.07, 0.49] | 0.35 [0.04, 0.96] |
| x2 | gradient_ratio | 0.82 [0.67, 0.88] | 0.92 [0.62, 1.26] |
| x2 | effective_blur_sigma_lr_px | 0.70 [0.50, 0.80] | 0.70 [0.40, 1.10] |
| x2 | noise_sigma_lr | 0.53 [0.19, 1.25] | 0.55 [0.11, 4.53] |
| x2 | temporal_residual_std | 2.57 [1.11, 21.46] | 2.45 [0.11, 16.86] |
| x2 | blockiness | 1.04 [1.01, 1.07] | 1.01 [0.95, 1.14] |
| x4 | bitrate_kbps | 445.90 [410.70, 451.90] | 563.35 [257.80, 1296.70] |
| x4 | luma_psnr_vs_area_down | 35.42 [32.01, 36.93] | 35.05 [25.75, 47.95] |
| x4 | hf_energy_ratio | 0.30 [0.28, 0.57] | 0.54 [0.18, 1.77] |
| x4 | gradient_ratio | 0.89 [0.82, 1.00] | 0.98 [0.74, 1.42] |
| x4 | effective_blur_sigma_lr_px | 0.60 [0.50, 0.70] | 0.50 [0.30, 0.90] |
| x4 | noise_sigma_lr | 1.23 [0.54, 1.40] | 0.95 [0.22, 6.29] |
| x4 | temporal_residual_std | 3.75 [2.53, 8.80] | 3.56 [0.29, 17.59] |
| x4 | blockiness | 0.98 [0.98, 1.05] | 1.01 [0.91, 1.20] |

By category (local, median PSNR vs area-downscaled reference / effective blur LR px / HF-energy ratio):

| factor | category | psnr | blur | hf | n |
|---|---|---|---|---|---|
| 2 | 3d_rendered | 38.946 | 0.7 | 0.418 | 24 |
| 2 | real_camera | 34.444 | 0.8 | 0.259 | 12 |
| 2 | screen | 29.324 | 0.6 | 0.322 | 12 |
| 4 | 3d_rendered | 38.196 | 0.5 | 0.559 | 24 |
| 4 | real_camera | 36.406 | 0.6 | 0.454 | 12 |
| 4 | screen | 30.374 | 0.5 | 0.56 | 12 |

- calibration run `v1_1`: 28 variants of CC0 references (reports/data/calibration_v1_1.json)
- calibration run `v1_2`: 28 variants of CC0 references (reports/data/calibration_v1_2.json)

## Interpretation (pilot, config 1.2 / 1.2.1) — hand-written; appended by create_report.py

- **Bitrate.** At <= 30 fps the local medians match practice (x2: 1424 kbps vs 1253; x4: 384 kbps vs 446).
  The overall local medians are higher because half the pilot is 50/60 fps material, which gets the
  (unpublished, assumed) 1.3-1.6x high-frame-rate multiplier; every CC0 practice item is <= 30 fps.
- **Effective blur / sharpness.** x2 medians match (blur 0.70 vs 0.70 LR px; HF ratio 0.35 vs 0.21, gradient
  0.92 vs 0.82). x4 local inputs are somewhat sharper than practice (<= 30 fps non-screen: blur 0.50 vs
  0.60, HF ratio 0.59 vs 0.30). Practice has only 3 x4 items, so this is weak evidence. **Open item for
  Phase B:** a modest increase of stage-1 blur for x4 (separate x2/x4 blur ranges) once more CC0 evidence
  exists, or keep the wider local distribution deliberately.
- **Noise.** Medians match (x2 0.55 vs 0.53; x4 0.95 vs 1.23). The large local maxima (up to 6.3) are
  estimator artefacts: in 8 of 9 such variants the downscaled reference itself scores higher (text edges,
  water texture), i.e. the Immerkaer estimate there measures content, not added noise.
- **Blocking.** No visible block structure after the final encode on either side (ratio ~1.0), as expected
  when JPEG-style blocks are added before a resize and a web encode.
- **Ranges are wider than practice by design.** Seven CC0 items cannot pin the hidden distribution; the local
  ranges deliberately cover mild-to-heavy cases around the practice medians.


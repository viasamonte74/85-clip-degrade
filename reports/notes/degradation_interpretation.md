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

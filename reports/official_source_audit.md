# Official source audit — sn85-upscaling-006 (read 2026-11-19)

## Identifiers used by this implementation

| Item | Value |
|---|---|
| Competition | `sn85-upscaling-006`, track `upscaling`, `upscaling_scoring: generative` |
| Manifest digest | `252bdd5ea46e8f4334bb0b3cec1d874ae61c23629dda6178555c49e3aa08a32c` |
| Commitment root | `f1dd7d37a731306fcd398378d7315b7111c1cec54d79f0227665eb2313ded9cd` |
| Scoring version (manifest) | `vidaio-scorer/1+a2572abe4686` (same id as the practice-pack baseline scores) |
| miner-vidaio commit | `6a6629da60b6883e831ad406d60dcd05df3e0a08` (2026-11-17, "comp 006 release bf9383c7a3") |
| validator-vidaio commit | `70a231bff929e007eff7154656260b870f438a3f` (2026-11-17) |
| Practice pack | release `practice-pack-006` (2026-11-19 10:19 UTC); README.md sha256 `1c1021586d1379131190d15809cbcaf5085d7b182c960dad2a8f26791e752d6c`, index.json sha256 `9c5b5495de312ee9b17abacc19ad55abe4965257fa6ebb4edc65b24b0a13fa9e` |
| Manifest source | public listing `GET https://95.133.254.122/competitions/v1/competitions/sn85-upscaling-006` (the hub page subnet.vidaio.io renders the same data) |

## Confirmed (public) requirements

- x2: 960x540 -> 1920x1080; x4: 480x270 -> 1920x1080; portrait mirrored (540x960 / 270x480 -> 1080x1920). `allowed_upscale_factors: [2, 4]`.
- Clips up to 10 s, constant frame rate up to 60 fps (24, 25, 30 and up to 60 in the practice pack); hidden set: 20 clips, 2297 output frames in total (~4 s per clip on average).
- Inputs: H.264 **or HEVC** at a web bitrate, MP4, tagged bt709 matrix + limited range (practice inputs: chroma "left"); 3 of 7 CC0 practice inputs are HEVC.
- References: FFV1, yuv420p 8-bit, BT.709, limited range.
- Kinds of hidden sources (practice README): Blender renders, screen content (rendered natively with open fonts), AI-generated clips. "The items are made the same way as hidden items (the same kinds of sources and the same degradation recipe), but no clip, shot, scene file seed or generation is shared with the hidden set."
- Degradation recipe (published in kind, practice README "How the inputs were made"):
  1. Stage one at the original resolution: optical blur (sometimes stronger in one direction); first resize to between the input size and about 1.7x it (area, bilinear, bicubic, Lanczos or spline); often temporal sensor-like noise (stronger on dark clips); sometimes JPEG-style block artefacts.
  2. Stage two: sometimes a slight second blur; the final resize to exactly the original divided by the factor; sometimes a little more noise.
  3. H.264 or H.265 at a platform bitrate (roughly 1-3.5 Mbps at 540p, 0.3-1.1 Mbps at 270p, more at 50/60 fps), 2-second GOP.
- Practice licences: p02-p08 CC0 (training permitted); p01, p09, p10 LTX-generated, evaluation only.
- Training-data rule (MINING.md "Licences"): commercial training only; CC0 / CC BY accepted; CC BY-SA accepted (ruling 2026-10-28); NC / ND / research-only rejected; fitting any setting to evaluation-only clips is not allowed.

## Not published (treated as experimental assumptions in config/degradation.yaml)

Per-item parameters and every distribution: blur sigma ranges and kernel shapes, the probability of each step, the
noise model and its levels, JPEG quality range, the exact resize implementations (antialiasing, kernel parameters),
encoder presets, rate-control mode, VBV, exact bitrate distribution and the 50/60 fps bitrate increase, whether
min-keyint / scene-cut key frames are used (scene-cut key frames are visible in p03), and the mix of difficulties.

## Measured on CC0 practice inputs (p02-p08 only)

See `reports/data/practice_cc0_stats.json` and `reports/degradation_analysis.md`: 540p inputs 0.91-1.70 Mbps
(HEVC ~0.9), 270p 0.41-0.45 Mbps; key frames every 2*fps frames plus scene cuts; B-frames; all 4.000 s; effective
blur 0.5-0.8 LR px; no visible JPEG blocking after the final encode. Evaluation-only items p01/p09/p10 were never
downloaded.

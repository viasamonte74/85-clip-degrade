# Dataset summary (pilot)

References: **24** originals from **17** independent source groups; degraded inputs: **96** (x2: 48, x4: 48).

## By category

| category | clips | groups | share |
|---|---|---|---|
| 3d_rendered | 12 | 7 | 50.0 % |
| real_camera | 6 | 4 | 25.0 % |
| screen | 6 | 6 | 25.0 % |

## By subcategory

| category | subcategory | clips |
|---|---|---|
| 3d_rendered | architecture_signs_text | 2 |
| 3d_rendered | cartoon_stylized | 2 |
| 3d_rendered | fast_motion | 3 |
| 3d_rendered | mechanical_rotating | 1 |
| 3d_rendered | natural_environment | 2 |
| 3d_rendered | reflective_particles_fluids | 2 |
| real_camera | animals_foliage_nature | 1 |
| real_camera | low_light_motion_blur | 2 |
| real_camera | people_hands_activity | 1 |
| real_camera | urban_vehicles | 1 |
| real_camera | water_rain_reflections | 1 |
| screen | code_editor | 1 |
| screen | dashboard_charts_tables | 1 |
| screen | documents_ui | 2 |
| screen | spreadsheet | 1 |
| screen | terminal_logs | 1 |

## Splits (group-aware)

| category | test | train | validation |
|---|---|---|---|
| 3d_rendered | 1 | 10 | 1 |
| real_camera | 1 | 4 | 1 |
| screen | 1 | 4 | 1 |

## Orientation, frame rate, duration

| orientation | clips |
|---|---|
| landscape | 19 |
| portrait | 5 |

| fps | clips |
|---|---|
| 24 | 5 |
| 25 | 2 |
| 30 | 5 |
| 60 | 9 |
| 60000/1001 | 3 |

| bucket | clips |
|---|---|
| 5-9 s (6-8 s) | 7 |
| 9-10 s (~10 s) | 3 |
| <=5 s (~4 s) | 14 |

## Degradation difficulty and codecs

| factor | difficulty | variants |
|---|---|---|
| 2 | heavy | 12 |
| 2 | medium | 18 |
| 2 | mild | 18 |
| 4 | heavy | 10 |
| 4 | medium | 20 |
| 4 | mild | 18 |

| factor | codec | variants |
|---|---|---|
| 2 | h264 | 29 |
| 2 | hevc | 19 |
| 4 | h264 | 30 |
| 4 | hevc | 18 |

| filter | resize1 | resize2 |
|---|---|---|
| area | 22 | 21 |
| bicubic | 24 | 25 |
| bilinear | 14 | 18 |
| lanczos | 15 | 9 |
| spline | 21 | 23 |

## Storage and throughput

- downloads (masters): 46.17 GB; references (FFV1): 3.77 GB; degraded inputs: 0.080 GB
- degradation: median 82.4 s per variant (4 variants per decode pass, nice 19 on a CPU quota shared with other jobs)
- reference preparation: median 74.7 s per reference

## Validation

```
{
 "reference/pass": 21,
 "reference/warn": 3,
 "source/pass": 16,
 "source/warn": 8,
 "variant/pass": 96
}
```
Split leaks: 0; near-duplicate pairs (dHash <= 8 bits): 0 (cross-split: 0).

# Licence audit

Asset-level evidence for every reference. Quotes were read from the URLs during collection.

| source_id | licence | commercial ML training | evidence | flags |
|---|---|---|---|---|
| cam_elfuente_boat | CC-BY-4.0 | yes | https://s3.amazonaws.com/download.opencontent.netflix.com/ElFuente/creative-commons-attribution-4-intl-public-license.txt | mirror contradiction (BY-NC-ND on Xiph copies) |
| cam_elfuente_market | CC-BY-4.0 | yes | https://s3.amazonaws.com/download.opencontent.netflix.com/ElFuente/creative-commons-attribution-4-intl-public-license.txt | privacy review, mirror contradiction (BY-NC-ND on Xiph copies) |
| cam_meridian | CC-BY-4.0 | yes | https://opencontent.netflix.com/; https://s3.amazonaws.com/download.opencontent.netflix.com/aom_test_materials/creative-commons-attribution-4-intl-public-license.txt; https://s3.amazonaws.com/download.opencontent.netflix.com/aom_test_materials/README_SDR.txt; https://github.com/vidAio-subnet/miner-vidaio/blob/main/docs/MINING.md | privacy review, mirror contradiction (BY-NC-ND on Xiph copies) |
| cam_nocturne | CC-BY-4.0 | yes | https://opencontent.netflix.com/; https://s3.amazonaws.com/download.opencontent.netflix.com/aom_test_materials/creative-commons-attribution-4-intl-public-license.txt; https://s3.amazonaws.com/download.opencontent.netflix.com/aom_test_materials/README_SDR.txt; https://github.com/vidAio-subnet/miner-vidaio/blob/main/docs/MINING.md | privacy review, mirror contradiction (BY-NC-ND on Xiph copies) |
| cam_sparks_a | CC-BY-4.0 | yes | https://opencontent.netflix.com/; https://s3.amazonaws.com/download.opencontent.netflix.com/aom_test_materials/creative-commons-attribution-4-intl-public-license.txt; https://s3.amazonaws.com/download.opencontent.netflix.com/aom_test_materials/README_SDR.txt; https://github.com/vidAio-subnet/miner-vidaio/blob/main/docs/MINING.md | privacy review, mirror contradiction (BY-NC-ND on Xiph copies) |
| cam_sparks_bp | CC-BY-4.0 | yes | https://opencontent.netflix.com/; https://s3.amazonaws.com/download.opencontent.netflix.com/aom_test_materials/creative-commons-attribution-4-intl-public-license.txt; https://s3.amazonaws.com/download.opencontent.netflix.com/aom_test_materials/README_SDR.txt; https://github.com/vidAio-subnet/miner-vidaio/blob/main/docs/MINING.md | privacy review, mirror contradiction (BY-NC-ND on Xiph copies) |
| r3d_bbb3d_0104 | CC-BY-3.0 | yes | https://media.xiph.org/BBB/bbb3d/README.txt; https://peach.blender.org/about/ |  |
| r3d_bbb3d_0601 | CC-BY-3.0 | yes | https://media.xiph.org/BBB/bbb3d/README.txt; https://peach.blender.org/about/ |  |
| r3d_bbb3d_1002p | CC-BY-3.0 | yes | https://media.xiph.org/BBB/bbb3d/README.txt; https://peach.blender.org/about/ |  |
| r3d_dweebs_a | CC-BY-SA-4.0 | yes | https://media.xiph.org/dweebs/README.txt | share-alike |
| r3d_dweebs_bp | CC-BY-SA-4.0 | yes | https://media.xiph.org/dweebs/README.txt | share-alike |
| r3d_own_city | CC0-1.0 | yes | src/sn85ds/blender/procedural_scenes.py |  |
| r3d_own_gears | CC0-1.0 | yes | src/sn85ds/blender/procedural_scenes.py |  |
| r3d_own_ocean_p | CC0-1.0 | yes | src/sn85ds/blender/procedural_scenes.py |  |
| r3d_own_signs | CC0-1.0 | yes | src/sn85ds/blender/procedural_scenes.py |  |
| r3d_sintel_city | CC-BY-3.0 | yes | https://media.xiph.org/sintel/README.txt |  |
| r3d_sintel_medallion | CC-BY-3.0 | yes | https://media.xiph.org/sintel/README.txt |  |
| r3d_sintel_rooftop | CC-BY-3.0 | yes | https://media.xiph.org/sintel/README.txt |  |
| scr_code | CC0-1.0 | yes | src/sn85ds/screen/ |  |
| scr_dashboard | CC0-1.0 | yes | src/sn85ds/screen/ |  |
| scr_document | CC0-1.0 | yes | src/sn85ds/screen/ |  |
| scr_phone_p | CC0-1.0 | yes | src/sn85ds/screen/ |  |
| scr_spreadsheet | CC0-1.0 | yes | src/sn85ds/screen/ |  |
| scr_terminal | CC0-1.0 | yes | src/sn85ds/screen/ |  |

## Rejected or deferred sources

| what | why | evidence |
|---|---|---|
| Xiph derf Netflix_* sequences (Chimera, El Fuente) and Xiph Meridian copy | CC BY-NC-ND 4.0 notices on those copies (non-commercial, no derivatives) | https://media.xiph.org/video/derf/Chimera/Netflix_DinnerScene_Copyright.txt |
| Amazon HDR education reel (derf) | CC BY-NC-ND 4.0 | https://media.xiph.org/video/derf/amazon/amazon_hdr_education_reel_final_121715_license.txt |
| SVT sequences on media.xiph.org/svt | 'They may be redistributed non-commercially' | https://media.xiph.org/svt/README.txt |
| Blackmagic Production Camera 4K shots (xiph-media/bmd) | no licence statement (README only says where they were retrieved from) | https://s3.amazonaws.com/xiph-media/bmd/bmpc4kshots/README.txt |
| Twitch game recordings (derf/twitch) | public-domain recordings but contain third-party copyrighted game content | https://media.xiph.org/video/derf/twitch/copyright.txt |
| Cosmos Laundromat 2K (Xiph PNG 2048x858; Netflix 2K HDR EXR) | below 1080 lines: a 1080p reference would require upscaling | frame header 2048x858 |
| Tears of Steel 1080bis PNG (1920x800) | below 1080 lines (the 4K TIFF set remains a candidate) | frame header 1920x800 |
| Elephants Dream via media.xiph.org | not rejected on licence (CC BY 2.5); deferred: the host served 1-2 KB/s during collection | https://orange.blender.org/ |
| TUM/LDV, hdgreetings, ITU/VQEG sequences in derf | research-only, commercial-site or unclear licences | https://media.xiph.org/video/derf/ |

## Attribution (required for CC BY / BY-SA material)

- **Big Buck Bunny — stereoscopic 4K 60 fps rework (left eye used)** — Big Buck Bunny (c) 2008 Blender Foundation | peach.blender.org; stereoscopic 4K 60 fps rework (c) 2013 Janus B. Kristensen | bbb3d.renderfarming.net; CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/)
- **Sintel (Durian Open Movie) — 4K PNG frames** — Sintel (c) copyright Blender Foundation | durian.blender.org; CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/)
- **The Daily Dweebs — lossless 8K mono TIFF frames** — The Daily Dweebs (c) Blender Animation Studio | dailydweebs.com; CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
- **Netflix Open Content — SDR shot segments (Sparks, Meridian, Nocturne) from aom_test_materials** — <title> (c) Netflix, Inc., Netflix Open Content, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)
- **Netflix Open Content — El Fuente test sequences (4K 60 fps 10-bit y4m)** — El Fuente (c) Netflix, Inc., Netflix Open Content, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)

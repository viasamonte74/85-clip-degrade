# Source inventory

| collection | category | licence | access | master |
|---|---|---|---|---|
| xiph_bbb3d | 3d_rendered | CC-BY-3.0 | https://s3.amazonaws.com/xiph-media/media.xiph.org/BBB/bbb3d/video/png/<scene>/<NNNN>.png (Xiph mirror on AWS Open Data; media.xiph.org itself was throttled to ~1 KB/s on 2026-11-19) | PNG 4000x4500 RGB 8-bit, left eye on top (4000x2250), 60 fps (README: 'monoscopic ... -mf fps=60') |
| xiph_sintel4k | 3d_rendered | CC-BY-3.0 | https://s3.amazonaws.com/xiph-media/media.xiph.org/sintel/sintel-4k-png/%08d.png ; shot picking on https://download.blender.org/demo/movies/Sintel.2010.1080p.mkv (md5 published alongside) | PNG 4096x1744 RGB 8-bit, 24 fps |
| xiph_dweebs8k | 3d_rendered | CC-BY-SA-4.0 | https://s3.amazonaws.com/xiph-media/media.xiph.org/dweebs/tif_8k_mono/%06d.tif | TIFF 8K mono (1440 frames) |
| netflix_sdr_segments | real_camera | CC-BY-4.0 | https://s3.amazonaws.com/download.opencontent.netflix.com/aom_test_materials/SDR/<title>/<first>-<last>.zip (JPEG 2000 frames, 10-bit 4:2:0, BT.709; members fetched individually by range) | J2K yuv420p10le; Sparks 4096x2160, Meridian/Nocturne 3840x2160; 59.94/60 fps (rate from the title: Sparks 59.94, Meridian 59.94, Nocturne 60) |
| netflix_elfuente | real_camera | CC-BY-4.0 | https://s3.amazonaws.com/download.opencontent.netflix.com/ElFuente/Netflix_<Name>_4096x2160_60fps_10bit_420.y4m (frames fetched by byte range: 44-byte header, 'FRAME\n' + 26,542,080 bytes each) | y4m 4096x2160 yuv420p10, header rate F60:1 |
| own_blender_procedural | 3d_rendered | CC0-1.0 (own work) | rendered locally, Blender 4.5.9 LTS | PNG 8-bit sRGB, procedural scenes |
| own_screen_render | screen | CC0-1.0 (own work) | rendered locally, headless Chromium | PNG screenshots, native 1080p |

## Clips

| source_id | category | subcategory | split | group | orientation | fps | frames | duration_s | mean_luma | cuts |
|---|---|---|---|---|---|---|---|---|---|---|
| cam_elfuente_boat | real_camera | water_rain_reflections | train | film_el_fuente | landscape | 60 | 240 | 4.0 | 0.3874 | 0 |
| cam_elfuente_market | real_camera | urban_vehicles | train | film_el_fuente | landscape | 60 | 240 | 4.0 | 0.1628 | 0 |
| cam_meridian | real_camera | people_hands_activity | validation | film_meridian | landscape | 60000/1001 | 360 | 6.006 | 0.3094 | 0 |
| cam_nocturne | real_camera | low_light_motion_blur | test | film_nocturne | landscape | 60 | 480 | 8.0 | 0.2692 | 0 |
| cam_sparks_a | real_camera | animals_foliage_nature | train | film_sparks | landscape | 60000/1001 | 240 | 4.004 | 0.3094 | 0 |
| cam_sparks_bp | real_camera | low_light_motion_blur | train | film_sparks | portrait | 60000/1001 | 240 | 4.004 | 0.2376 | 0 |
| r3d_bbb3d_0104 | 3d_rendered | natural_environment | train | film_big_buck_bunny | landscape | 60 | 240 | 4.0 | 0.3888 | 0 |
| r3d_bbb3d_0601 | 3d_rendered | fast_motion | train | film_big_buck_bunny | landscape | 60 | 240 | 4.0 | 0.631 | 0 |
| r3d_bbb3d_1002p | 3d_rendered | natural_environment | train | film_big_buck_bunny | portrait | 60 | 240 | 4.0 | 0.2755 | 0 |
| r3d_dweebs_a | 3d_rendered | cartoon_stylized | train | film_daily_dweebs | landscape | 24 | 96 | 4.0 | 0.3835 | 0 |
| r3d_dweebs_bp | 3d_rendered | cartoon_stylized | train | film_daily_dweebs | portrait | 24 | 96 | 4.0 | 0.4131 | 0 |
| r3d_own_city | 3d_rendered | fast_motion | train | own_blender_city_s14 | landscape | 60 | 240 | 4.0 | 0.099 | 0 |
| r3d_own_gears | 3d_rendered | mechanical_rotating | validation | own_blender_gears_s11 | landscape | 30 | 300 | 10.0 | 0.3761 | 0 |
| r3d_own_ocean_p | 3d_rendered | reflective_particles_fluids | train | own_blender_ocean_s13 | portrait | 30 | 120 | 4.0 | 0.4051 | 0 |
| r3d_own_signs | 3d_rendered | architecture_signs_text | test | own_blender_signs_s12 | landscape | 25 | 150 | 6.0 | 0.7616 | 0 |
| r3d_sintel_city | 3d_rendered | fast_motion | train | film_sintel | landscape | 24 | 180 | 7.5 | 0.4052 | 0 |
| r3d_sintel_medallion | 3d_rendered | reflective_particles_fluids | train | film_sintel | landscape | 24 | 144 | 6.0 | 0.1707 | 0 |
| r3d_sintel_rooftop | 3d_rendered | architecture_signs_text | train | film_sintel | landscape | 24 | 96 | 4.0 | 0.4882 | 0 |
| scr_code | screen | code_editor | train | own_screen_code_s202 | landscape | 60 | 360 | 6.0 | 0.1047 | 0 |
| scr_dashboard | screen | dashboard_charts_tables | validation | own_screen_dashboard_s204 | landscape | 25 | 250 | 10.0 | 0.1506 | 0 |
| scr_document | screen | documents_ui | test | own_screen_document_s205 | landscape | 60 | 240 | 4.0 | 0.0949 | 0 |
| scr_phone_p | screen | documents_ui | train | own_screen_phone_s206 | portrait | 30 | 180 | 6.0 | 0.1429 | 0 |
| scr_spreadsheet | screen | spreadsheet | train | own_screen_spreadsheet_s201 | landscape | 30 | 300 | 10.0 | 0.9268 | 0 |
| scr_terminal | screen | terminal_logs | train | own_screen_terminal_s203 | landscape | 30 | 120 | 4.0 | 0.1589 | 0 |

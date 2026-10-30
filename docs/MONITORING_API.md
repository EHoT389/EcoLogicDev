# Monitoring API

The router is independent of existing project calculations and authentication. It only reads preprocessed Sentinel-2 L2A products from `MONITORING_DATA_DIR` (automatic default: validated `backend/storage/monitoring-city`, otherwise the central pilot `backend/storage/monitoring`; an explicit non-empty environment override wins). No network retrieval or full-scene processing happens during a page request.

`GET /api/monitoring/periods` and `/metadata` describe availability, season, identified scenes, source, grid, scope and limitations. `status=unavailable` is returned when products are absent, unfinished, corrupt, misaligned, not 10 m EPSG:32643, larger than 2 million pilot pixels or 25 million city grid pixels, or missing two identified source scenes per year. Such responses contain null measurements.

`GET /api/monitoring/changes?threshold=0.3` returns statistics for the selected dataset AOI; `scope=administrative_city` means the verified OSM relation 5501700, including subordinate/unbuilt territory. `GET /api/monitoring/zones/{zone_id}?threshold=0.3` uses the canonical OSM polygon and pixel-centre rasterization (`all_touched=False`). It never changes the zone status. Threshold is finite and bounded 0.10–0.90. The comparison is fixed to June 1–August 31 in 2020 and 2026.

Statistics use only the intersection of valid pixels in both years, with at least two good observations in each year. Areas use 100 m² per cell. `comparable_fraction` is relative to the selected portion inside the grid; `aoi_coverage_fraction` explicitly reports partial geographical coverage. No common pixels means null areas and means. A zero base vegetation area means null percentage change.

`GET /api/monitoring/tiles/{year}/{z}/{x}/{y}?threshold=0.3` supports `year=2020`, `2026`, `changes`; zoom 8–19; valid XYZ indices. PNG RGBA uses nearest-neighbour raster projection. Green is gain, red loss, grey no vegetation-class transition, transparent no comparable data. Single-year layers share the comparison mask. The in-process cache is bounded (1 validated dataset; 64 PNG tiles; 32 small city statistics records), keyed by manifest and TIFF file modification signatures.

`GET /api/monitoring/export?format=pdf|xlsx&zone_id=...&threshold=0.3` generates RU/KK reports according to `Accept-Language`. They contain measured statistics, the change raster, a two-period NDVI chart, method, source scene IDs/dates/cloud cover and caveats. Unavailable/no-data exports return HTTP 409 instead of fabricated numbers. Excel protects user-readable strings against formula interpretation.

For AI, `get_vegetation_change(zone_id, period_start=2020, period_end=2026, threshold=.3, language='ru')` reads the same validated server results. It has no cloud calls and cannot be supplied client measurements.

Tests in `tests/test_monitoring_api.py` create explicitly labelled analytical raster fixtures in temporary directories. These fixtures are not satellite observations and never enter production data directories.


City grids are read in 512×512 native windows; display uses bounded WarpedVRT reads. `layer=vegetation|ndvi|quality` selects classification, continuous NDVI or minimum valid observation count across the two seasons. Quality colours: grey <2, amber 2–3, green ≥4; transparent outside the AOI. This is an observation count, not a statistical confidence score. Changes/vegetation/NDVI use a shared valid comparison mask. The quality layer explicitly shows insufficient observations.

"""Fetch a real city Sentinel catalog; optionally cache bounded raw source bands."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.monitoring.city_catalog import DEFAULT_BOUNDARY, DEFAULT_OUTPUT, build_city_catalog, ensure_crop, load_boundary, atomic_json

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boundary', default=str(DEFAULT_BOUNDARY))
    parser.add_argument('--output', default=str(DEFAULT_OUTPUT))
    parser.add_argument('--per-month', type=int, default=2)
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--download', action='store_true', help='Cache only AOI-intersecting raw B04/B08/SCL windows')
    parser.add_argument('--workers', type=int, choices=(1, 2), default=2, help='At most two independent public source reads')
    args = parser.parse_args()
    catalog = build_city_catalog(args.output, args.boundary, args.per_month, args.refresh)
    if args.download:
        boundary = load_boundary(args.boundary)
        jobs = [(scene, band) for period in catalog.values() for scene in period['features'] for band in ('red', 'nir', 'scl')]
        index = {}
        with ThreadPoolExecutor(max_workers=args.workers) as workers:
            pending = {workers.submit(ensure_crop, scene, band, boundary, Path(args.output) / 'source-crops'): (scene, band) for scene, band in jobs}
            for future in as_completed(pending):
                scene, band = pending[future]
                path = future.result()
                index.setdefault(scene['id'], {})[band] = str(path.resolve())
        atomic_json(Path(args.output) / 'source-crops-index.json', index)
        print('All source cutouts complete: '+str(len(jobs)), flush=True)

if __name__ == '__main__':
    main()

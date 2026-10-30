import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.monitoring.rgb_pipeline import build_rgb, DEFAULT_OUTPUT, DEFAULT_BOUNDARY

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Build real RGB from the exact city NDVI acquisitions')
    parser.add_argument('--output',default=str(DEFAULT_OUTPUT))
    parser.add_argument('--boundary',default=str(DEFAULT_BOUNDARY))
    parser.add_argument('--download-only',action='store_true')
    args=parser.parse_args()
    build_rgb(args.output,args.boundary,args.download_only)

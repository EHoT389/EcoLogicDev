"""Offline city AOI pipeline; run from the repository root."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.monitoring.city_pipeline import main
if __name__ == '__main__':
    main()

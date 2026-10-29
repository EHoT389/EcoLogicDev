"""Run from the repository root: python scripts/build_monitoring.py."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.monitoring.pipeline import main
if __name__ == '__main__':
    main()

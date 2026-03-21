"""
tests/conftest.py
──────────────────
Pytest configuration — adds src/ to the Python path so imports
like `from handlers.ingest_event import lambda_handler` work
without needing the `src.` prefix (matching the Lambda runtime).
"""

import sys
import os

# Add src/ to the path so test imports mirror Lambda runtime imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

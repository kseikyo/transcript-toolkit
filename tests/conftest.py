import sys
from pathlib import Path

# Add scripts/ to import path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import json


@pytest.fixture
def sample_corrections():
    """Load sample corrections from fixtures."""
    path = Path(__file__).parent / "fixtures" / "sample-corrections.json"
    return json.loads(path.read_text())


@pytest.fixture
def sample_profile():
    """Load sample profile from fixtures."""
    path = Path(__file__).parent / "fixtures" / "sample-profile.json"
    return json.loads(path.read_text())


@pytest.fixture
def sample_transcript():
    """Load sample raw transcript from fixtures."""
    path = Path(__file__).parent / "fixtures" / "sample-raw-transcript.md"
    return path.read_text()


@pytest.fixture
def global_corrections():
    """Load global corrections."""
    path = Path(__file__).parent.parent / "corrections-global.json"
    return json.loads(path.read_text())

import os
import sys
import tempfile
from pathlib import Path

_APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_APP.parents[1] / "packages"))
sys.path.insert(0, str(_APP))

# ambiente de teste ANTES de importar o app: dados em tmp, mock instantâneo
os.environ["NOEMI_DATA_DIR"] = tempfile.mkdtemp(prefix="noemi-test-")
os.environ["MOCK_DELAY_S"] = "0"
os.environ["WORKER_POLL_S"] = "0.05"
os.environ.pop("MOCK_MODE", None)  # default = mock

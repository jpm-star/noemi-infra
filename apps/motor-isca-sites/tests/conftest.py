import os
import sys
import tempfile
from pathlib import Path

_APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_APP))  # pra importar builder_web

# ambiente de teste ANTES de importar o app: publica num tmp, não em /var/www/sites
os.environ["SITE_OUT_DIR"] = tempfile.mkdtemp(prefix="site-test-")
os.environ["SITE_BASE_URL"] = "https://go.noemi.digital"
_MOTOR_SITE = os.environ.setdefault("MOTOR_SITE_DIR", "/root/motor-site")
if os.path.isdir(_MOTOR_SITE):  # ponte já na coleta, senão importorskip pula limpo
    sys.path.insert(0, _MOTOR_SITE)

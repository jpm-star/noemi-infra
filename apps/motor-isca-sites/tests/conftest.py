import os
import sys
import tempfile
from pathlib import Path

_APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_APP))  # pra importar builder_web / auth
sys.path.insert(0, str(_APP.parents[1] / "packages"))  # shared_core (histórico)

# ambiente de teste ANTES de importar o app: publica num tmp, não em /var/www/sites
_TMP = tempfile.mkdtemp(prefix="studio-test-")
os.environ["SITE_OUT_DIR"] = _TMP
os.environ["SITE_BASE_URL"] = "https://go.noemi.digital"
os.environ["STUDIO_INSECURE_COOKIE"] = "1"  # TestClient usa http; sem isso o cookie some
os.environ["BUILDER_AUTH_FILE"] = str(Path(_TMP) / "builder_auth_test.json")
_MOTOR_SITE = os.environ.setdefault("MOTOR_SITE_DIR", "/root/motor-site")
if os.path.isdir(_MOTOR_SITE):  # ponte já na coleta, senão importorskip pula limpo
    sys.path.insert(0, _MOTOR_SITE)

import auth  # noqa: E402

auth.definir_senha("senha-teste")  # semeia hash (usuario = joaop)

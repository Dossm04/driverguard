import importlib.util
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location("dg_tunnel", Path(__file__).parents[1] / "tunnel.py")
tunnel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tunnel)


@pytest.mark.parametrize("code", [403, 429, 500, 503])
def test_inconclusive_auth_check_blocks_tunnel(code):
    error = urllib.error.HTTPError("http://localhost", code, "test", {}, None)
    with patch.object(tunnel.urllib.request, "urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match=str(code)):
            tunnel.default_credentials_in_use()


def test_rejected_default_credentials_are_safe():
    error = urllib.error.HTTPError("http://localhost", 401, "test", {}, None)
    with patch.object(tunnel.urllib.request, "urlopen", side_effect=error):
        assert tunnel.default_credentials_in_use() == []


def test_unreachable_backend_blocks_tunnel():
    with patch.object(tunnel.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")):
        with pytest.raises(RuntimeError, match="недоступен"):
            tunnel.default_credentials_in_use()

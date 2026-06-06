from __future__ import annotations
import functools
import inspect
import importlib
import importlib.util
import logging
import os
import subprocess
import sys
import json
from pathlib import Path
from typing import Dict, List, Literal, Optional, Any

logger = logging.getLogger(__name__)

# Module-level script template - compiled once
_INTROSPECT_SCRIPT_TEMPLATE = '''
import importlib
import inspect
import sys
import json

package_name = {package_name!r}
mode = {mode!r}

try:
    module = importlib.import_module(package_name)
    symbols = dir(module)
    
    public_symbols = []
    for s in symbols:
        if s.startswith('_'):
            continue
        try:
            val = getattr(module, s)
            if inspect.isfunction(val) or inspect.isclass(val) or inspect.ismodule(val):
                public_symbols.append(s)
        except Exception:
            continue
            
    result = {{package_name: public_symbols}}
    print(json.dumps(result))
except Exception as e:
    sys.stderr.write(str(e))
    sys.exit(1)
'''

class ThirdPartyIntrospector:
    """
    Live introspection of installed third-party packages.
    Runs introspection in a subprocess for safety to prevent hanging or crashes in the main process.
    """
    
    def __init__(self, mode: Literal["shallow", "deep"] = "shallow", timeout_seconds: int = 5):
        self.mode = mode
        self.timeout_seconds = timeout_seconds

    def introspect_python(self, package_name: str, venv_path: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect Python package using a subprocess to run a retrieval script.
        Uses module-level script template for better performance.
        """
        script = _INTROSPECT_SCRIPT_TEMPLATE.format(
            package_name=package_name,
            mode=self.mode
        )
        env = os.environ.copy()

        # Try venv python first, then fallback to current
        python_bins = [sys.executable]
        if venv_path:
            venv_python = venv_path / "bin" / "python"
            if not venv_python.exists():
                venv_python = venv_path / "Scripts" / "python.exe"  # Windows
            if venv_python.exists():
                python_bins.insert(0, str(venv_python))

        for python_bin in python_bins:
            try:
                res = subprocess.run(
                    [python_bin, "-c", script],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    env=env
                )
                if res.returncode == 0:
                    return json.loads(res.stdout)
                else:
                    logger.debug(f"Introspection failed for {package_name} with {python_bin}: {res.stderr[:200]}")
            except subprocess.TimeoutExpired:
                logger.warning(f"Introspection timeout for {package_name}")
            except Exception as e:
                logger.debug(f"Introspection error for {package_name}: {e}")

        return {}

    def introspect_npm(self, package_name: str, node_modules_path: Path) -> Dict[str, List[str]]:
        """
        Basic introspection for npm packages by looking at their package.json or index.d.ts.
        This is a placeholder for v1.
        """
        # Node.js introspection usually involves parsing exports from package.json
        # or scanning the root index file for exported names.
        return {}

from __future__ import annotations
import inspect
import importlib
import importlib.util
import os
import subprocess
import sys
import json
from pathlib import Path
from typing import Dict, List, Literal, Optional, Any

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
        """
        script = f"""
import importlib
import inspect
import sys
import json

package_name = {repr(package_name)}
mode = {repr(self.mode)}

try:
    module = importlib.import_module(package_name)
    symbols = dir(module)
    
    # Filter for public symbols that are functions or classes
    public_symbols = []
    for s in symbols:
        if s.startswith('_'): continue
        try:
            val = getattr(module, s)
            if inspect.isfunction(val) or inspect.isclass(val) or inspect.ismodule(val):
                public_symbols.append(s)
        except Exception:
            continue
            
    result = {{package_name: public_symbols}}
    
    if mode == "deep":
        # Basic recursion into public submodules (if requested in the future)
        pass
        
    print(json.dumps(result))
except Exception as e:
    sys.exit(1)
"""
        env = os.environ.copy()
        if venv_path:
            # Point to the venv's python executable
            python_bin = venv_path / "bin" / "python"
            if not python_bin.exists():
                python_bin = venv_path / "Scripts" / "python.exe" # Windows check
            
            if python_bin.exists():
                try:
                    res = subprocess.run(
                        [str(python_bin), "-c", script],
                        capture_output=True,
                        text=True,
                        timeout=self.timeout_seconds,
                        env=env
                    )
                    if res.returncode == 0:
                        return json.loads(res.stdout)
                except Exception:
                    pass
        
        # Fallback to current environment python
        try:
            res = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=env
            )
            if res.returncode == 0:
                return json.loads(res.stdout)
        except Exception:
            pass
            
        return {}

    def introspect_npm(self, package_name: str, node_modules_path: Path) -> Dict[str, List[str]]:
        """
        Basic introspection for npm packages by looking at their package.json or index.d.ts.
        This is a placeholder for v1.
        """
        # Node.js introspection usually involves parsing exports from package.json
        # or scanning the root index file for exported names.
        return {}

from __future__ import annotations
import functools
import inspect
import importlib
import importlib.util
import structlog
import os
import re
import subprocess
import sys
import json
from pathlib import Path
from typing import Dict, List, Literal, Optional, Any

from batho.utils.path_sanitizer import PathSecurityError, safe_join

logger = structlog.get_logger(__name__)


def _is_safe_dependency_name(name: str) -> bool:
    """Reject names that could be used for path traversal or unsafe globs."""
    if not name or not isinstance(name, str):
        return False
    if "\0" in name or "\\" in name or name.startswith("/"):
        return False
    return ".." not in name.split("/")

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
        if not re.match(r'^[a-zA-Z0-9_.-]+$', package_name):
            logger.warning(f"Invalid package name rejected: {package_name}")
            return {}
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
        Introspect npm packages by parsing package.json exports and .d.ts files.
        Returns {package_name: [exported_symbol_names]}.
        """
        if not _is_safe_dependency_name(package_name):
            logger.warning("invalid_npm_package_name", package_name=package_name)
            return {}

        try:
            pkg_dir = safe_join(node_modules_path, package_name)
        except PathSecurityError:
            logger.warning("npm_package_path_unsafe", package_name=package_name)
            return {}

        if not pkg_dir.is_dir():
            return {}

        result: Dict[str, List[str]] = {}
        symbols: List[str] = []

        # 1. Parse package.json for exports / main / types
        pkg_json_path = pkg_dir / "package.json"
        if pkg_json_path.is_file():
            try:
                pkg_data = json.loads(pkg_json_path.read_text(encoding="utf-8", errors="ignore"))
                # Collect exported names from `exports` field
                exports = pkg_data.get("exports")
                if isinstance(exports, dict):
                    for export_key, export_val in exports.items():
                        if export_key.startswith("."):
                            if isinstance(export_val, str):
                                symbols.append(export_key.strip("./"))
                            elif isinstance(export_val, dict):
                                # types/require/import/etc.
                                for v in export_val.values():
                                    if isinstance(v, str):
                                        symbols.append(v.split("/")[-1].replace(".js", "").replace(".d.ts", ""))
                # main entry
                main = pkg_data.get("main")
                if isinstance(main, str):
                    symbols.append(main.split("/")[-1].replace(".js", ""))
                # types entry
                types = pkg_data.get("types") or pkg_data.get("typings")
                if isinstance(types, str):
                    symbols.append(types.split("/")[-1].replace(".d.ts", ""))
            except Exception as exc:
                logger.debug(f"npm package.json parse failed for {package_name}: {exc}")

        # 2. Scan index.d.ts for exported names (export declarations)
        dts_files = list(pkg_dir.glob("*.d.ts")) + list(pkg_dir.glob("index.d.ts"))
        if not dts_files:
            # Try dist/
            dist_dir = pkg_dir / "dist"
            if dist_dir.is_dir():
                dts_files = list(dist_dir.glob("*.d.ts"))
        for dts_file in dts_files[:3]:  # limit to 3 files
            try:
                content = dts_file.read_text(encoding="utf-8", errors="ignore")
                # Match: export { foo, bar }; export default foo; export const foo; export function foo
                for match in re.finditer(
                    r'export\s+(?:default\s+)?(?:const|let|var|function|class|interface|type|enum)\s+(\w+)',
                    content,
                ):
                    symbols.append(match.group(1))
                # Match: export { foo, bar, baz }
                for match in re.finditer(r'export\s*\{([^}]+)\}', content):
                    for name in match.group(1).split(","):
                        name = name.strip().split(" as ")[0].strip()
                        if name and not name.startswith("//"):
                            symbols.append(name)
            except Exception as exc:
                logger.debug(f"npm .d.ts parse failed for {dts_file}: {exc}")

        # Deduplicate and filter
        unique = sorted({s for s in symbols if s and not s.startswith("_") and re.match(r'^[a-zA-Z_$][\w$]*$', s)})
        if unique:
            result[package_name] = unique
        return result

    def introspect_crate(self, crate_name: str, version_spec: str | None = None) -> Dict[str, List[str]]:
        """
        Introspect Rust crates by parsing source files in the cargo registry cache.
        Returns {crate_name: [public_item_names]}.
        """
        if not _is_safe_dependency_name(crate_name):
            logger.warning("invalid_crate_name", crate_name=crate_name)
            return {}

        # Common cargo registry source paths
        home = Path.home()
        cargo_paths = [
            home / ".cargo" / "registry" / "src",
        ]
        # CARGO_HOME override
        cargo_home = os.environ.get("CARGO_HOME")
        if cargo_home:
            cargo_paths.insert(0, Path(cargo_home) / "registry" / "src")

        crate_dir: Path | None = None
        for cargo_src in cargo_paths:
            if not cargo_src.is_dir():
                continue
            # Registry dirs are hashed: e.g. index.crates.io-1949cf8c6b5b557f/
            for reg_dir in cargo_src.iterdir():
                if not reg_dir.is_dir():
                    continue
                # Try exact name or name-version
                candidates: list[Path] = []
                try:
                    candidates.append(safe_join(reg_dir, crate_name))
                except PathSecurityError:
                    continue
                if version_spec:
                    # version_spec may be like "1.0" or ">=1.0,<2.0" — try prefix
                    ver_clean = re.match(r'[\d.]+', version_spec)
                    if ver_clean:
                        try:
                            candidates.append(safe_join(reg_dir, f"{crate_name}-{ver_clean.group()}"))
                        except PathSecurityError:
                            pass
                # Also try any dir starting with crate_name-
                if not any(c.is_dir() for c in candidates):
                    for d in reg_dir.iterdir():
                        if d.is_dir() and (d.name == crate_name or d.name.startswith(f"{crate_name}-")):
                            try:
                                candidates.append(safe_join(d))
                            except PathSecurityError:
                                continue
                            break
                for c in candidates:
                    if c.is_dir():
                        crate_dir = c
                        break
                if crate_dir:
                    break
            if crate_dir:
                break

        if crate_dir is None:
            return {}

        symbols: List[str] = []
        src_dir = crate_dir / "src"
        if not src_dir.is_dir():
            src_dir = crate_dir
        # Parse lib.rs and mod.rs files for pub items
        for rs_file in [src_dir / "lib.rs", src_dir / "main.rs"] + list(src_dir.glob("*.rs"))[:5]:
            if not rs_file.is_file():
                continue
            try:
                content = rs_file.read_text(encoding="utf-8", errors="ignore")
                # Match: pub fn foo, pub struct Foo, pub enum Foo, pub trait Foo, pub mod foo, pub use foo
                for match in re.finditer(
                    r'pub\s+(?:async\s+)?(?:fn|struct|enum|trait|mod|use|const|static|type)\s+(\w+)',
                    content,
                ):
                    symbols.append(match.group(1))
            except Exception as exc:
                logger.debug(f"crate .rs parse failed for {rs_file}: {exc}")

        unique = sorted({s for s in symbols if s and not s.startswith("_")})
        if unique:
            return {crate_name: unique}
        return {}

    def introspect_go_module(self, module_name: str, version_spec: str | None = None) -> Dict[str, List[str]]:
        """
        Introspect Go modules by parsing source files in the GOPATH module cache.
        Returns {module_name: [exported_symbol_names]}.
        """
        if not _is_safe_dependency_name(module_name):
            logger.warning("invalid_go_module_name", module_name=module_name)
            return {}

        gopath = os.environ.get("GOPATH") or str(Path.home() / "go")
        mod_cache = Path(gopath) / "pkg" / "mod"
        if not mod_cache.is_dir():
            return {}

        # Module dirs are lowercase + versioned: e.g. github.com/gin-gonic/gin@v1.9.1
        module_lower = module_name.lower()
        mod_dir: Path | None = None
        # Try exact match or version-suffixed
        for d in mod_cache.rglob("*"):
            if d.is_dir():
                d_name_lower = d.name.lower()
                if d_name_lower == module_lower or d_name_lower.startswith(f"{module_lower}@"):
                    try:
                        mod_dir = safe_join(d)
                    except PathSecurityError:
                        continue
                    break
        if mod_dir is None:
            return {}

        symbols: List[str] = []
        # Parse .go files for exported identifiers (capitalized names)
        go_files = list(mod_dir.rglob("*.go"))[:10]  # limit to 10 files
        for go_file in go_files:
            try:
                content = go_file.read_text(encoding="utf-8", errors="ignore")
                # In Go, exported names start with uppercase
                # Match: func Foo, type Foo struct, type Foo interface, var Foo, const Foo
                for match in re.finditer(
                    r'^(?:func|type|var|const)\s+([A-Z]\w*)',
                    content,
                    re.MULTILINE,
                ):
                    symbols.append(match.group(1))
            except Exception as exc:
                logger.debug(f"go .go parse failed for {go_file}: {exc}")

        unique = sorted({s for s in symbols if s and s[0].isupper()})
        if unique:
            return {module_name: unique}
        return {}

    def introspect_jar(self, artifact_name: str, version_spec: str | None = None) -> Dict[str, List[str]]:
        """
        Introspect Java artifacts by parsing source/javadoc jars or local source dirs.
        Returns {artifact_name: [class_names]}.
        """
        if not artifact_name or not isinstance(artifact_name, str):
            return {}

        # Try common Maven local repository paths
        home = Path.home()
        m2_paths = [
            home / ".m2" / "repository",
        ]
        maven_home = os.environ.get("MAVEN_REPO") or os.environ.get("M2_REPO")
        if maven_home:
            m2_paths.insert(0, Path(maven_home))

        # artifact_name may be "groupId:artifactId" — convert to path
        parts = artifact_name.replace(":", "/").split("/")
        artifact_dir: Path | None = None
        for m2 in m2_paths:
            if not m2.is_dir():
                continue
            try:
                candidate = safe_join(m2, *parts)
            except PathSecurityError:
                continue
            if candidate.is_dir():
                artifact_dir = candidate
                break
            # Try just the last part as artifactId
            if len(parts) >= 2:
                try:
                    group_path = safe_join(m2, *parts[:-1])
                except PathSecurityError:
                    continue
                if group_path.is_dir():
                    for d in group_path.iterdir():
                        if d.is_dir() and d.name == parts[-1]:
                            try:
                                artifact_dir = safe_join(d)
                            except PathSecurityError:
                                continue
                            break
            if artifact_dir:
                break

        symbols: List[str] = []
        if artifact_dir and artifact_dir.is_dir():
            # Parse source jars (*.jar with -sources suffix) or .java files
            source_jars = list(artifact_dir.glob("*-sources.jar"))
            for jar in source_jars[:2]:
                try:
                    import zipfile
                    with zipfile.ZipFile(jar, "r") as zf:
                        for name in zf.namelist():
                            if name.endswith(".java"):
                                # Class name from file path: com/foo/Bar.java -> Bar
                                cls = name.rsplit("/", 1)[-1].replace(".java", "")
                                if cls and cls[0].isupper():
                                    symbols.append(cls)
                except Exception as exc:
                    logger.debug(f"jar parse failed for {jar}: {exc}")

        # Fallback: minimal entry with artifact name
        if not symbols:
            return {artifact_name: [artifact_name.split(":")[-1]]}

        unique = sorted({s for s in symbols if s and s[0].isupper()})
        if unique:
            return {artifact_name: unique}
        return {}

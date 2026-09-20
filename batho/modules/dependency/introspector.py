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
    if "\0" in name or "\\" in name or name.startswith("/") or name.startswith("-"):
        return False
    return ".." not in name.split("/")


def _extract_from_files(
    files: List[Path], patterns: List["re.Pattern[str]"], limit: int = 500
) -> List[str]:
    """Extract first capture-group matches from text files (bounded).

    Shared by the file-parsing introspectors (gem, pub, spm, ...): reads with
    ``errors="ignore"``, applies every pattern, stops at ``limit`` names.
    """
    names: List[str] = []
    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in patterns:
            for m in pat.finditer(content):
                names.append(m.group(1))
                if len(names) >= limit:
                    return names
    return names

# Module-level script template - compiled once
# Resolves the dist name to real import name(s): dist metadata top_level.txt /
# RECORD top-level dirs first, then normalized fallbacks (hyphen->underscore).
# Results are keyed by the IMPORT name (what source code references), not the
# dist name — e.g. pyyaml -> yaml, tree-sitter -> tree_sitter.
_INTROSPECT_SCRIPT_TEMPLATE = '''
import importlib
import importlib.metadata
import inspect
import sys
import json
import re

package_name = {package_name!r}
mode = {mode!r}

def _candidates(name):
    cands = []
    try:
        dist = importlib.metadata.distribution(name)
        tl = dist.read_text("top_level.txt")
        if tl and tl.strip():
            for m in tl.split():
                if m not in cands:
                    cands.append(m)
        else:
            for f in (dist.files or []):
                top = f.parts[0] if f.parts else ""
                if top.endswith(".py"):
                    top = top[:-3]
                if top and top.isidentifier() and not top.endswith(("-info", ".dist-info")) and top not in cands:
                    cands.append(top)
    except Exception:
        pass
    for c in (name.replace("-", "_").lower(), name.lower()):
        if c not in cands:
            cands.append(c)
    return cands

try:
    result = {{}}
    for cand in _candidates(package_name)[:5]:
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", cand):
            continue
        try:
            module = importlib.import_module(cand)
        except Exception:
            continue
        public_symbols = []
        for s in dir(module):
            if s.startswith('_'):
                continue
            try:
                val = getattr(module, s)
                # ismodule or callable: covers classes, plain functions, AND
                # C-extension/Cython callables (pyarrow.schema, numpy.array)
                # which inspect.isfunction misses.
                if inspect.ismodule(val) or callable(val):
                    public_symbols.append(s)
            except Exception:
                continue
        result[cand] = public_symbols
    if not result:
        sys.stderr.write("no importable candidate for " + package_name)
        sys.exit(1)
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

    def introspect_python(self, package_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect Python package using a subprocess to run a retrieval script.
        Uses module-level script template for better performance.

        Only the project venv (``env_path``) is introspected — never the
        interpreter running Batho itself (``sys.executable``), which would
        register wrong-env symbols. No venv → ``{}`` (the dep-01 skip policy
        decides upstream).
        """
        venv_path = env_path
        if not re.match(r'^[a-zA-Z0-9_.-]+$', package_name):
            logger.warning(f"Invalid package name rejected: {package_name}")
            return {}

        # Resolve venv python binaries (posix + Windows layouts)
        python_bins: list[str] = []
        if venv_path:
            for sub, exe in (("bin", "python"), ("Scripts", "python.exe"), ("bin", "python3")):
                candidate = venv_path / sub / exe
                if candidate.exists():
                    python_bins.append(str(candidate))

        if not python_bins:
            return {}

        script = _INTROSPECT_SCRIPT_TEMPLATE.format(
            package_name=package_name,
            mode=self.mode
        )
        env = os.environ.copy()

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

    def introspect_npm(self, package_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect npm packages by parsing package.json exports and .d.ts files.
        ``env_path`` is the project's ``node_modules`` dir (project-scoped env
        per the dep-01 matrix); missing env → {} (skip policy).
        Returns {package_name: [exported_symbol_names]}.
        """
        if env_path is None or not env_path.is_dir():
            return {}
        node_modules_path = env_path
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

    def introspect_crate(self, crate_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect Rust crates by parsing source files in the cargo registry cache.
        ``env_path`` (the dep-01 matrix resolution) is consulted first.
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
        # dep-01 matrix hint (e.g. CARGO_HOME/registry/src resolved upstream)
        if env_path is not None:
            cargo_paths.insert(0, env_path)

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

    def introspect_go_module(self, module_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect Go modules by parsing source files in the GOPATH module cache.
        ``env_path`` (the dep-01 matrix resolution) is consulted first.
        Returns {module_name: [exported_symbol_names]}.
        """
        if not _is_safe_dependency_name(module_name):
            logger.warning("invalid_go_module_name", module_name=module_name)
            return {}

        if env_path is not None and env_path.is_dir():
            mod_cache = env_path
        else:
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

    def introspect_jar(self, artifact_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect JVM artifacts (Java/Kotlin/Scala) by parsing source jars —
        or binary jar entry names when no ``-sources`` variant exists — from
        the Maven local repository and the Gradle module cache
        (``~/.gradle/caches/modules-2/files-2.1``).
        Returns {artifact_name: [class_names]}. No store found → {} (skip).
        """
        if not artifact_name or not isinstance(artifact_name, str):
            return {}

        group: str | None = None
        artifact: str = artifact_name
        if ":" in artifact_name:
            group, artifact = artifact_name.split(":", 1)

        # Path segments must be traversal-safe; dots are valid maven/gradle
        # group segments, so they are only rejected as full ".." segments.
        def _safe_segments(*parts: str) -> list[str] | None:
            out: list[str] = []
            for p in parts:
                if not p or p in (".", "..") or "/" in p or "\\" in p or "\0" in p:
                    return None
                out.append(p)
            return out

        want_ver: str | None = None
        if version_spec:
            m = re.match(r"[\d.]+", version_spec)
            if m:
                want_ver = m.group()

        # Store roots: Maven local repo first, then the Gradle module cache.
        store_bases: list[tuple[Path, bool]] = []  # (root, is_gradle)
        if env_path is not None:
            store_bases.append((env_path, "files-2.1" in env_path.parts))
        for var in ("MAVEN_REPO", "M2_REPO"):
            val = os.environ.get(var)
            if val:
                store_bases.append((Path(val), False))
        store_bases.append((Path.home() / ".m2" / "repository", False))
        gradle_user = os.environ.get("GRADLE_USER_HOME") or str(Path.home() / ".gradle")
        store_bases.append((Path(gradle_user) / "caches" / "modules-2" / "files-2.1", True))

        symbols: List[str] = []
        for root, is_gradle in store_bases:
            if not root.is_dir():
                continue
            # m2: <group dots→slashes>/<artifact>/<version>/
            # gradle: files-2.1/<group.dotted>/<artifact>/<version>/
            if is_gradle:
                segments = _safe_segments(*(([group] if group else []) + [artifact]))
            else:
                segments = _safe_segments(*(((group.split(".") if group else []) + [artifact])))
            if not segments:
                continue
            try:
                artifact_base = safe_join(root, *segments)
            except PathSecurityError:
                continue
            if not artifact_base.is_dir():
                continue

            version_dirs = [d for d in artifact_base.iterdir() if d.is_dir()]
            if not version_dirs:
                version_dirs = [artifact_base]  # flat layout (env_path hint)
            if want_ver:
                matching = [d for d in version_dirs if d.name.startswith(want_ver)]
                version_dirs = matching or version_dirs
            version_dirs.sort(key=lambda d: d.name)

            for vdir in version_dirs[-2:]:  # newest two versions
                # rglob: gradle nests jars under per-hash dirs
                source_jars = sorted(vdir.rglob("*-sources.jar"))
                for jar in source_jars[:2]:
                    symbols.extend(self._class_names_from_jar(jar, sources=True))
                if not source_jars:
                    # Binary jar: entry names only (no extraction).
                    for jar in sorted(vdir.rglob("*.jar"))[:1]:
                        symbols.extend(self._class_names_from_jar(jar, sources=False))
                if symbols:
                    break
            if symbols:
                break

        unique = sorted({s for s in symbols if s and s[0].isupper()})
        if unique:
            return {artifact_name: unique}
        return {}

    @staticmethod
    def _class_names_from_jar(jar_path: Path, sources: bool) -> List[str]:
        """Class names from a jar: .java entries (sources) or .class entry
        basenames (binary). Bounded to 2000 entries; never extracts content."""
        import zipfile
        names: List[str] = []
        try:
            with zipfile.ZipFile(jar_path, "r") as zf:
                for name in zf.namelist()[:2000]:
                    if sources and name.endswith(".java"):
                        cls = name.rsplit("/", 1)[-1].replace(".java", "")
                        if cls and cls[0].isupper():
                            names.append(cls)
                    elif not sources and name.endswith(".class"):
                        cls = name.rsplit("/", 1)[-1].replace(".class", "")
                        # Strip Kotlin/compiler suffixes ($Inner, Kt)
                        cls = cls.split("$")[0]
                        if cls.endswith("Kt"):
                            cls = cls[:-2] or cls
                        if cls and cls[0].isupper():
                            names.append(cls)
        except Exception as exc:
            logger.debug(f"jar parse failed for {jar_path}: {exc}")
        return names

    # ------------------------------------------------------------------
    # Universal introspection (dep-03 … dep-15). All methods share the
    # uniform signature (name, version_spec, env_path, project_root) so the
    # indexer dispatches through _LANGUAGE_INTROSPECTORS. Missing env/store
    # → {} (the dep-01 skip policy decides upstream; no {name: [name]} stubs).
    # ------------------------------------------------------------------

    def introspect_gem(self, gem_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect Ruby gems by parsing lib/**/*.rb of the installed gem.
        Gem dir resolution: ``env_path`` → GEM_HOME → BUNDLE_PATH → ``~/.gem``
        (ruby/*/ layout) → ``gem env gemdir`` subprocess (last resort).
        Returns {gem_name: [module/class/def names]}.
        """
        if not _is_safe_dependency_name(gem_name):
            logger.warning("invalid_gem_name", gem_name=gem_name)
            return {}

        gem_dir = env_path or self._resolve_gem_dir()
        if gem_dir is None or not gem_dir.is_dir():
            return {}

        gems_root = gem_dir / "gems"
        if not gems_root.is_dir():
            gems_root = gem_dir

        # Locate the gem dir: exact name first, then name-<version> dirs.
        candidates: list[Path] = []
        try:
            exact = safe_join(gems_root, gem_name)
            if exact.is_dir():
                candidates.append(exact)
        except PathSecurityError:
            return {}
        try:
            siblings = sorted(gems_root.iterdir())
        except OSError:
            siblings = []
        for d in siblings:
            if d.is_dir() and d.name.startswith(f"{gem_name}-"):
                candidates.append(d)
        if not candidates:
            return {}

        # Prefer version-prefix match when a spec is given.
        gem_root = candidates[0]
        if version_spec:
            ver = re.match(r"[\d.]+", version_spec)
            if ver:
                for c in candidates:
                    if c.name == f"{gem_name}-{ver.group()}":
                        gem_root = c
                        break

        lib = gem_root / "lib"
        if not lib.is_dir():
            return {}

        # The gem's own entry file first (its declared API), then the rest.
        files = [lib / f"{gem_name}.rb"] + [
            f for f in sorted(lib.rglob("*.rb"))
            if f.is_file() and "spec" not in f.parts and "test" not in f.parts
        ]
        files = [f for f in files if f.is_file()][:10]

        symbols = _extract_from_files(files, [
            re.compile(r"^\s*module\s+([A-Z]\w*)", re.MULTILINE),
            re.compile(r"^\s*class\s+([A-Z]\w*)", re.MULTILINE),
            re.compile(r"^\s*def\s+(?:self\.)?([a-zA-Z_]\w*[?!=]?)", re.MULTILINE),
        ])
        unique = sorted({s for s in symbols if s and not s.startswith("_")})
        if unique:
            return {gem_name: unique}
        return {}

    @staticmethod
    def _resolve_gem_dir() -> Path | None:
        """Resolve the installed-gems directory (GEM_HOME → BUNDLE_PATH →
        ~/.gem/ruby/*/ → ``gem env gemdir`` subprocess)."""
        for var in ("GEM_HOME", "BUNDLE_PATH"):
            val = os.environ.get(var)
            if val and Path(val).is_dir():
                return Path(val)
        home_gem = Path.home() / ".gem"
        if home_gem.is_dir():
            for ruby_dir in sorted(home_gem.glob("ruby/*")):
                if ruby_dir.is_dir():
                    return ruby_dir
        try:
            res = subprocess.run(
                ["gem", "env", "gemdir"],
                capture_output=True, text=True, timeout=5,
            )
            if res.returncode == 0:
                p = Path(res.stdout.strip())
                if p.is_dir():
                    return p
        except (OSError, subprocess.TimeoutExpired):
            pass
        return None

    def introspect_composer(self, package_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect PHP/Hack packages from the project's vendor/ dir
        (project-scoped env). ``package_name`` is "vendor/pkg". Symbols are
        class/interface/trait/enum/function names, namespace-qualified via
        PSR-4 or the file's ``namespace`` declaration so
        Symfony\\Component\\Yaml\\Yaml-style refs resolve.
        """
        if not _is_safe_dependency_name(package_name):
            logger.warning("invalid_composer_package_name", package_name=package_name)
            return {}
        if env_path is None or not env_path.is_dir():
            return {}
        vendor_path = env_path

        try:
            pkg_dir = safe_join(vendor_path, package_name)
        except PathSecurityError:
            logger.warning("composer_package_path_unsafe", package_name=package_name)
            return {}
        if not pkg_dir.is_dir():
            return {}

        # PSR-4 mapping from the package's own composer.json → namespace roots
        namespaces: list[tuple[str, str]] = []
        pkg_json = pkg_dir / "composer.json"
        if pkg_json.is_file():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
                psr4 = ((data.get("autoload") or {}).get("psr-4")) or {}
                if isinstance(psr4, dict):
                    for ns, path in psr4.items():
                        if isinstance(path, str) and path:
                            namespaces.append((ns.strip("\\"), path.strip("/")))
            except Exception as exc:
                logger.debug(f"composer.json parse failed for {package_name}: {exc}")

        scan_dirs = [pkg_dir / p for _, p in namespaces] or [pkg_dir / "src", pkg_dir / "lib"]
        php_files: list[Path] = []
        for d in scan_dirs:
            if d.is_dir():
                php_files = [
                    f for f in sorted(d.rglob("*.php"))
                    if f.is_file() and not any(s in f.parts for s in ("tests", "Tests", "Fixtures"))
                ][:15]
                if php_files:
                    break

        decl = re.compile(r"^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait|enum)\s+([A-Za-z_]\w*)", re.MULTILINE)
        fn = re.compile(r"^\s*function\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE)
        ns_re = re.compile(r"^\s*namespace\s+([\w\\]+)\s*;", re.MULTILINE)

        symbols: list[str] = []
        for f in php_files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            ns_match = ns_re.search(content)
            ns = ns_match.group(1) if ns_match else ""
            for m in decl.finditer(content):
                short = m.group(1)
                symbols.append(short)
                if ns:
                    symbols.append(f"{ns}\\{short}")
            for m in fn.finditer(content):
                symbols.append(m.group(1))

        unique = sorted({s for s in symbols if s and not s.startswith("_")})
        if unique:
            return {package_name: unique}
        return {}

    def introspect_nuget(self, package_id: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect NuGet packages from the global packages folder
        (NUGET_PACKAGES → ~/.nuget/packages). Symbol source: XML doc files
        (``lib/<tfm>/*.xml``, ``<member name="T:...">``); .nuspec metadata is
        a metadata-level fallback. Returns {package_id: [type_names]}.
        """
        if not _is_safe_dependency_name(package_id):
            logger.warning("invalid_nuget_package_id", package_id=package_id)
            return {}

        packages_root = env_path
        if packages_root is None:
            val = os.environ.get("NUGET_PACKAGES")
            packages_root = Path(val) if val else Path.home() / ".nuget" / "packages"
        if not packages_root.is_dir():
            return {}

        pkg_dir = packages_root / package_id.lower()
        if not pkg_dir.is_dir():
            return {}

        version_dirs = sorted(d.name for d in pkg_dir.iterdir() if d.is_dir())
        if not version_dirs:
            return {}
        chosen: str | None = None
        if version_spec:
            ver = re.match(r"[\d.]+", version_spec)
            if ver:
                for v in version_dirs:
                    if v.startswith(ver.group()):
                        chosen = v
                        break
        if chosen is None:
            chosen = version_dirs[-1]  # lexicographic ~ latest
        ver_dir = pkg_dir / chosen

        symbols: list[str] = []
        lib_dir = ver_dir / "lib"
        doc_files: list[Path] = []
        if lib_dir.is_dir():
            for tfm in sorted(lib_dir.iterdir()):
                if tfm.is_dir():
                    docs = sorted(tfm.glob("*.xml"))
                    if docs:
                        doc_files = docs[:3]
                        break
        for f in doc_files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in re.finditer(r'<member\s+name="T:([\w.]+)"', content):
                full = m.group(1)
                # Strip generic arity suffixes (List`1 style docs use {T})
                full = full.split("`")[0]
                symbols.append(full.rsplit(".", 1)[-1])
                symbols.append(full)

        if not symbols:
            for f in sorted(ver_dir.glob("*.nuspec"))[:1]:
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for m in re.finditer(r'<dependency\s+id="([\w.\-]+)"', content):
                    symbols.append(m.group(1))

        unique = sorted({s for s in symbols if s})
        if unique:
            return {package_id: unique}
        return {}

    def introspect_pub(self, package_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect Dart packages. Primary source: the project's
        .dart_tool/package_config.json (exact rootUri per package — the same
        mechanism dart itself uses); fallback: PUB_CACHE (~/.pub-cache)
        hosted layout. Parses lib/**/*.dart public declarations.
        """
        if not _is_safe_dependency_name(package_name):
            logger.warning("invalid_pub_package_name", package_name=package_name)
            return {}

        lib_dir: Path | None = None
        if project_root is not None:
            pc = project_root / ".dart_tool" / "package_config.json"
            if pc.is_file():
                try:
                    data = json.loads(pc.read_text(encoding="utf-8", errors="ignore"))
                    for entry in data.get("packages", []):
                        if entry.get("name") != package_name:
                            continue
                        root_uri = entry.get("rootUri", "")
                        if not root_uri or ("://" in root_uri and not root_uri.startswith("file:")):
                            continue
                        raw = root_uri[len("file://"):] if root_uri.startswith("file://") else root_uri
                        root = Path(raw) if os.path.isabs(raw) else (pc.parent / raw)
                        cand = root / "lib"
                        if cand.is_dir():
                            lib_dir = cand
                            break
                except Exception as exc:
                    logger.debug(f"package_config.json parse failed: {exc}")

        if lib_dir is None:
            cache = env_path
            if cache is None:
                val = os.environ.get("PUB_CACHE")
                cache = Path(val) if val else Path.home() / ".pub-cache"
            hosted = cache / "hosted" / "pub.dev"
            base = hosted if hosted.is_dir() else cache
            if base.is_dir():
                for d in sorted(base.iterdir()):
                    if d.is_dir() and (d.name == package_name or d.name.startswith(f"{package_name}-")):
                        cand = d / "lib"
                        if cand.is_dir():
                            lib_dir = cand
                            break

        if lib_dir is None:
            return {}

        dart_files = [f for f in sorted(lib_dir.rglob("*.dart")) if f.is_file()][:10]
        keywords = {"if", "for", "while", "switch", "return", "catch", "assert",
                   "await", "yield", "new", "throw", "print", "else", "do"}
        symbols = _extract_from_files(dart_files, [
            re.compile(r"^\s*(?:abstract\s+)?class\s+(\w+)", re.MULTILINE),
            re.compile(r"^\s*mixin\s+(\w+)", re.MULTILINE),
            re.compile(r"^\s*extension\s+(\w+)", re.MULTILINE),
            re.compile(r"^\s*enum\s+(\w+)", re.MULTILINE),
            re.compile(r"^\s*typedef\s+(\w+)", re.MULTILINE),
            re.compile(r"^(?!(?:return|if|for|while|switch|catch|throw|assert|await|yield|new)\b)[A-Za-z_][\w<>?,.\s\[\]]*?\s+([a-z_]\w*)\s*[({<]", re.MULTILINE),
        ])
        unique = sorted({s for s in symbols if s and s not in keywords and not s.startswith("_")})
        if unique:
            return {package_name: unique}
        return {}

    def introspect_julia(self, package_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect Julia packages from the depot (JULIA_DEPOT_PATH → ~/.julia).
        ``export`` lists in src/<Name>.jl are the explicit public API and take
        priority; falls back to parsed module/function/struct definitions.
        """
        if not _is_safe_dependency_name(package_name):
            logger.warning("invalid_julia_package_name", package_name=package_name)
            return {}

        depot = env_path
        if depot is None:
            val = os.environ.get("JULIA_DEPOT_PATH")
            if val:
                first = val.split(os.pathsep)[0]
                depot = Path(first) if first else None
            else:
                depot = Path.home() / ".julia"
        if depot is None or not depot.is_dir():
            return {}

        pkg_root = depot / "packages" / package_name
        if not pkg_root.is_dir():
            packages_dir = depot / "packages"
            if not packages_dir.is_dir():
                return {}
            for d in sorted(packages_dir.iterdir()):
                if d.is_dir() and d.name.lower() == package_name.lower():
                    pkg_root = d
                    break
            else:
                return {}

        slug_dirs = [d for d in sorted(pkg_root.iterdir()) if d.is_dir()]
        if not slug_dirs:
            return {}

        src = slug_dirs[0] / "src"
        if not src.is_dir():
            return {}
        jl_files = [src / f"{package_name}.jl"] + [f for f in sorted(src.glob("*.jl")) if f.is_file()]
        jl_files = [f for f in jl_files if f.is_file()][:8]

        exports: list[str] = []
        defs: list[str] = []
        for f in jl_files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in re.finditer(r"^\s*export\s+([^\n]+)", content, re.MULTILINE):
                for part in m.group(1).split(","):
                    name = part.strip()
                    if name and re.match(r"^[A-Za-z_]\w*$", name):
                        exports.append(name)
            for m in re.finditer(r"^\s*(?:mutable\s+)?struct\s+(\w+)", content, re.MULTILINE):
                defs.append(m.group(1))
            for m in re.finditer(r"^\s*function\s+(\w+)", content, re.MULTILINE):
                defs.append(m.group(1))
            for m in re.finditer(r"^\s*abstract\s+type\s+(\w+)", content, re.MULTILINE):
                defs.append(m.group(1))
            for m in re.finditer(r"^\s*module\s+(\w+)", content, re.MULTILINE):
                defs.append(m.group(1))

        chosen = sorted(set(exports)) or sorted({d for d in defs if d and not d.startswith("_")})
        if chosen:
            return {package_name: chosen}
        return {}

    def introspect_cran(self, package_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect R packages. Library resolution: project renv/library
        (via ``project_root``) → ``env_path`` → R_LIBS_USER env → platform
        default library. The NAMESPACE file's ``export`` directives are the
        exact public API. Returns {package_name: [symbols]}.
        """
        if not _is_safe_dependency_name(package_name):
            logger.warning("invalid_cran_package_name", package_name=package_name)
            return {}

        pkg_dir: Path | None = None
        if project_root is not None:
            renv_lib = project_root / "renv" / "library"
            if renv_lib.is_dir():
                for d in renv_lib.rglob(package_name):
                    if d.is_dir() and (d / "NAMESPACE").is_file():
                        pkg_dir = d
                        break
        if pkg_dir is None:
            roots: list[Path] = []
            if env_path is not None:
                roots.append(env_path)
            val = os.environ.get("R_LIBS_USER")
            if val:
                roots.extend(Path(e) for e in val.split(os.pathsep) if e)
            home = Path.home()
            if sys.platform == "darwin":
                roots.extend(sorted(home.glob("Library/R/*/library")))
            else:
                roots.extend(sorted(home.glob("R/*-library/*")))
            for root in roots:
                cand = root / package_name
                if (cand / "NAMESPACE").is_file():
                    pkg_dir = cand
                    break
        if pkg_dir is None:
            return {}

        try:
            content = (pkg_dir / "NAMESPACE").read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return {}

        symbols: list[str] = []
        for m in re.finditer(r"^\s*export\(([^)]*)\)", content, re.MULTILINE):
            for part in m.group(1).split(","):
                name = part.strip().strip("\"'")
                if name and re.match(r"^[A-Za-z_.][\w.]*$", name):
                    symbols.append(name)
        for kw in ("exportClasses", "exportMethods", "S3method"):
            for m in re.finditer(rf"^\s*{kw}\(([^)]*)\)", content, re.MULTILINE):
                for part in m.group(1).split(","):
                    name = part.strip().strip("\"'")
                    if name and re.match(r"^\w+$", name):
                        symbols.append(name)

        if not symbols and re.search(r"^\s*exportPattern\(", content, re.MULTILINE):
            # Pattern export: enumerate top-level objects from R/ sources.
            r_dir = pkg_dir / "R"
            files = []
            if r_dir.is_dir():
                files = [f for f in sorted(r_dir.glob("*.R")) + sorted(r_dir.glob("*.r")) if f.is_file()][:15]
            symbols = _extract_from_files(files, [
                re.compile(r"^([A-Za-z_.][\w.]*)\s*<-\s*function", re.MULTILINE),
            ])

        unique = sorted(set(s for s in symbols if s))
        if unique:
            return {package_name: unique}
        return {}

    def introspect_cabal(self, package_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect Haskell packages from the cabal store. ``exposed-modules``
        in the .cabal file is the exact public API (module names double as
        symbols). Falls back to ``ghc-pkg`` when no .cabal file is found.
        """
        if not _is_safe_dependency_name(package_name):
            logger.warning("invalid_cabal_package_name", package_name=package_name)
            return {}

        root = env_path or Path.home() / ".cabal"
        hackage = root / "packages" / "hackage.haskell.org" / package_name
        modules: list[str] = []
        if hackage.is_dir():
            versions = sorted(d.name for d in hackage.iterdir() if d.is_dir())
            if version_spec:
                ver = re.match(r"[\d.]+", version_spec)
                if ver:
                    versions = [v for v in versions if v.startswith(ver.group())] or versions
            for v in reversed(versions):  # newest first
                cabal_file = hackage / v / f"{package_name}.cabal"
                if not cabal_file.is_file():
                    continue
                try:
                    content = cabal_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                in_section = False
                for line in content.splitlines():
                    m = re.match(r"^\s*(exposed-modules|reexported-modules):\s*(.*)", line)
                    if m:
                        in_section = True
                        for tok in m.group(2).split():
                            # re-exports look like "M" or "pkg:M as N"
                            modules.append(tok.split(":")[-1].split(" ")[0])
                    elif in_section:
                        if not line.strip() or not line.startswith((" ", "\t")):
                            in_section = False
                        else:
                            for tok in line.split():
                                modules.append(tok.split(":")[-1].split(" ")[0])
                if modules:
                    break

        if not modules:
            # ghc-pkg fallback (user/global package db; binary-missing → skip)
            try:
                res = subprocess.run(
                    ["ghc-pkg", "field", package_name, "exposed-modules", "--simple-output"],
                    capture_output=True, text=True, timeout=self.timeout_seconds,
                )
                if res.returncode == 0 and res.stdout.strip():
                    modules = res.stdout.split()
            except (OSError, subprocess.TimeoutExpired):
                pass

        unique = sorted({m for m in modules if m})
        if unique:
            return {package_name: unique}
        return {}

    def introspect_spm(self, package_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect Swift package checkouts under .build/checkouts (SPM is
        project-scoped — ``env_path`` is the checkouts dir). Only ``public``
        and ``open`` declarations are extracted: the package's real API.
        """
        if not _is_safe_dependency_name(package_name):
            logger.warning("invalid_spm_package_name", package_name=package_name)
            return {}
        if env_path is None or not env_path.is_dir():
            return {}

        pkg_dir = env_path / package_name
        sources = pkg_dir / "Sources"
        if not sources.is_dir():
            return {}
        swift_files = [f for f in sorted(sources.rglob("*.swift")) if f.is_file()][:12]
        symbols = _extract_from_files(swift_files, [
            re.compile(r"^\s*(?:@\w+\s+)*(?:public|open)\s+(?:final\s+|static\s+)*class\s+(\w+)", re.MULTILINE),
            re.compile(r"^\s*(?:@\w+\s+)*public\s+(?:final\s+|static\s+)*struct\s+(\w+)", re.MULTILINE),
            re.compile(r"^\s*public\s+enum\s+(\w+)", re.MULTILINE),
            re.compile(r"^\s*public\s+protocol\s+(\w+)", re.MULTILINE),
            re.compile(r"^\s*public\s+typealias\s+(\w+)", re.MULTILINE),
            re.compile(r"^\s*public\s+func\s+(\w+)", re.MULTILINE),
            re.compile(r"^\s*public\s+var\s+(\w+)", re.MULTILINE),
            re.compile(r"^\s*public\s+extension\s+(\w+)", re.MULTILINE),
        ])
        unique = sorted({s for s in symbols if s and not s.startswith("_")})
        if unique:
            return {package_name: unique}
        return {}

    def introspect_zigmod(self, package_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect Zig module deps: vendored ``.zigmod/deps/`` (via
        ``project_root``) first, then the zig global package cache (hash dirs
        matched by their build.zig.zon ``.name`` field). Parses ``pub``
        declarations. Returns {package_name: [names]}.
        """
        if not _is_safe_dependency_name(package_name):
            logger.warning("invalid_zigmod_name", package_name=package_name)
            return {}

        source_dir: Path | None = None
        if project_root is not None:
            vendored = project_root / ".zigmod" / "deps"
            if vendored.is_dir():
                cand = vendored / package_name
                if (cand / "build.zig.zon").is_file() or list(cand.glob("*.zig")):
                    source_dir = cand
        if source_dir is None:
            cache = env_path
            if cache is None:
                val = os.environ.get("ZIG_GLOBAL_CACHE_DIR")
                cache = Path(val) if val else Path.home() / ".cache" / "zig" / "p"
            if cache.is_dir():
                for d in list(cache.iterdir())[:50]:
                    if not d.is_dir():
                        continue
                    zon = d / "build.zig.zon"
                    if not zon.is_file():
                        continue
                    try:
                        content = zon.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
                    if re.search(r"\.name\s*=\s*[.\"]*" + re.escape(package_name) + r"\b", content):
                        source_dir = d
                        break
        if source_dir is None:
            return {}

        zig_files = [f for f in sorted(source_dir.rglob("*.zig")) if f.is_file()][:8]
        symbols = _extract_from_files(zig_files, [
            re.compile(r"^\s*pub\s+fn\s+(\w+)", re.MULTILINE),
            re.compile(r"^\s*pub\s+const\s+(\w+)", re.MULTILINE),
            re.compile(r"^\s*pub\s+var\s+(\w+)", re.MULTILINE),
        ])
        unique = sorted({s for s in symbols if s and s != "main"})
        if unique:
            return {package_name: unique}
        return {}

    def introspect_rebar3(self, dep_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect Erlang deps from _build/default/lib/<dep>/src/*.erl
        (project-scoped — ``env_path`` is the lib dir). ``-export([...]).``
        lists are the explicit public API; ``-module(name).`` gives the module
        symbol. Returns {dep_name: [names]}.
        """
        if not _is_safe_dependency_name(dep_name):
            logger.warning("invalid_rebar3_dep", dep_name=dep_name)
            return {}
        if env_path is None or not env_path.is_dir():
            return {}

        src = env_path / dep_name / "src"
        if not src.is_dir():
            return {}
        erl_files = [f for f in sorted(src.glob("*.erl")) if f.is_file()][:10]

        symbols: list[str] = []
        for f in erl_files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in re.finditer(r"^\s*-module\(\s*(\w+)\s*\)\s*\.", content, re.MULTILINE):
                symbols.append(m.group(1))
            for m in re.finditer(r"-export\(\s*\[(.*?)\]\s*\)\s*\.", content, re.DOTALL):
                for entry in m.group(1).split(","):
                    name = entry.strip().split("/")[0].strip()
                    if name and re.match(r"^[a-z_]\w*$", name):
                        symbols.append(name)

        unique = sorted(set(s for s in symbols if s))
        if unique:
            return {dep_name: unique}
        return {}

    def introspect_opam(self, package_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect OCaml packages from the opam root (OPAMROOT → ~/.opam;
        switch from OPAMSWITCH → <root>/config → "default"). .mli interface
        files are the exact public API; falls back to top-level ``let`` in
        .ml implementations. Returns {package_name: [names]}.
        """
        if not _is_safe_dependency_name(package_name):
            logger.warning("invalid_opam_package_name", package_name=package_name)
            return {}

        root = env_path
        if root is None:
            val = os.environ.get("OPAMROOT")
            root = Path(val) if val else Path.home() / ".opam"
        if not root.is_dir():
            return {}

        switch = os.environ.get("OPAMSWITCH")
        if not switch:
            config = root / "config"
            if config.is_file():
                try:
                    m = re.search(r"^switch:\s*(\S+)", config.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
                    if m:
                        switch = m.group(1)
                except OSError:
                    pass
        if not switch:
            switch = "default"

        lib = root / switch / "lib" / package_name
        if not lib.is_dir():
            return {}

        mli_files = [f for f in sorted(lib.rglob("*.mli")) if f.is_file()][:8]
        symbols = _extract_from_files(mli_files, [
            re.compile(r"^\s*val\s+([a-z_]\w*)", re.MULTILINE),
            # type t | type 'a t | type ('a, 'b) t — capture the type name
            # (last lowercase identifier of the declaration head).
            re.compile(r"^\s*type\s+(?:'[^=]*?\s+)*\(*[^=]*?\)*\s*([a-z_]\w*)\s*(?:=|$)", re.MULTILINE),
            re.compile(r"^\s*module\s+([A-Z]\w*)", re.MULTILINE),
            re.compile(r"^\s*exception\s+([A-Z]\w*)", re.MULTILINE),
        ])
        if not symbols:
            ml_files = [f for f in sorted(lib.rglob("*.ml")) if f.is_file()][:8]
            symbols = _extract_from_files(ml_files, [
                re.compile(r"^\s*let\s+([a-z_]\w*)", re.MULTILINE),
            ])
        unique = sorted({s for s in symbols if s and not s.startswith("_")})
        if unique:
            return {package_name: unique}
        return {}

    def introspect_luarocks(self, rock_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect Lua rocks from the luarocks tree (LUAROCKS → ~/.luarocks).
        Module tables (``function M.f`` style) are the dominant export
        pattern. Returns {rock_name: [names]}.
        """
        if not _is_safe_dependency_name(rock_name):
            logger.warning("invalid_rock_name", rock_name=rock_name)
            return {}

        root = env_path
        if root is None:
            val = os.environ.get("LUAROCKS")
            root = Path(val) if val else Path.home() / ".luarocks"
        if not root.is_dir():
            return {}

        candidates: list[Path] = []
        share = root / "share" / "lua"
        if share.is_dir():
            for ver_dir in sorted(share.iterdir()):
                if not ver_dir.is_dir():
                    continue
                f = ver_dir / f"{rock_name}.lua"
                if f.is_file():
                    candidates.append(f)
                d = ver_dir / rock_name
                if d.is_dir():
                    init = d / "init.lua"
                    if init.is_file():
                        candidates.append(init)
                    candidates.extend(sorted(d.glob("*.lua"))[:5])
        for rocks_dir in sorted(root.glob("lib/luarocks/rocks-*")):
            rock_dir = rocks_dir / rock_name
            if rock_dir.is_dir():
                candidates.extend(sorted(rock_dir.rglob("*.lua")))

        files = [f for f in candidates if f.is_file()][:8]
        symbols = _extract_from_files(files, [
            re.compile(r"^\s*function\s+(?:[\w.]+\.)?(\w+)\s*\(", re.MULTILINE),
            re.compile(r"^\s*([a-zA-Z_]\w*)\s*=\s*function", re.MULTILINE),
        ])
        unique = sorted({s for s in symbols if s and not s.startswith("_")})
        if unique:
            return {rock_name: unique}
        return {}

    def introspect_cpan(self, module_name: str, version_spec: str | None = None, env_path: Path | None = None, project_root: Path | None = None) -> Dict[str, List[str]]:
        """
        Introspect Perl modules from local::lib-style trees (PERL5LIB →
        ~/perl5/lib/perl5). System ``@INC`` is never probed (skip policy).
        Module names use ``::`` separators (Try::Tiny → Try/Tiny.pm).
        """
        if not _is_safe_dependency_name(module_name):
            logger.warning("invalid_cpan_module_name", module_name=module_name)
            return {}

        # cpanfile parsing stores dist-form names (Try::Tiny → Try-Tiny);
        # module files live under ::-separated paths — accept both spellings.
        module_name = module_name.replace("-", "::")

        root = env_path
        if root is None:
            val = os.environ.get("PERL5LIB")
            if val:
                for entry in val.split(os.pathsep):
                    if entry and Path(entry).is_dir():
                        root = Path(entry)
                        break
            else:
                root = Path.home() / "perl5" / "lib" / "perl5"
        if root is None or not root.is_dir():
            return {}

        rel = module_name.replace("::", "/")
        mod_file = root / f"{rel}.pm"
        if not mod_file.is_file():
            mod_file = root / rel / f"{module_name.rsplit('::', 1)[-1]}.pm"
        if not mod_file.is_file():
            return {}

        try:
            content = mod_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return {}
        symbols: list[str] = []
        for m in re.finditer(r"^\s*package\s+([\w:]+)\s*;", content, re.MULTILINE):
            symbols.append(m.group(1))
        for m in re.finditer(r"^\s*sub\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            symbols.append(m.group(1))
        unique = sorted({s for s in symbols if s and not s.startswith("_")})
        if unique:
            return {module_name: unique}
        return {}

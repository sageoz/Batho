import os
import tempfile
from pathlib import Path
from batho.modules.dependency.manifest_parser import ManifestParser
from batho.modules.dependency.stdlib_tables import StdlibSymbolTable

def test_stdlib():
    print("Testing StdlibSymbolTable...")
    st = StdlibSymbolTable()
    python_json = st.get_symbols("python", "json")
    print(f"Python json symbols: {python_json}")
    assert "dumps" in python_json
    assert st.is_stdlib_module("python", "json")
    assert not st.is_stdlib_module("python", "unknown_module")
    print("StdlibSymbolTable OK")

def test_manifest_parser():
    print("Testing ManifestParser...")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # Create requirements.txt
        reqs = tmp_path / "requirements.txt"
        reqs.write_text("requests==2.31.0\nnumpy>=1.2.3")
        
        # Create package.json
        pkg = tmp_path / "package.json"
        pkg.write_text('{"dependencies": {"express": "^4.18.2"}}')
        
        parser = ManifestParser()
        deps = parser.parse_manifests(tmp_path)
        
        for d in deps:
            print(f"Found dep: {d.name} {d.version_spec} ({d.manager.value})")
            
        names = [d.name for d in deps]
        assert "requests" in names
        assert "numpy" in names
        assert "express" in names
        print("ManifestParser OK")

if __name__ == "__main__":
    test_stdlib()
    test_manifest_parser()
    print("All verification tests passed!")

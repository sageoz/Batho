import os
import tempfile
from pathlib import Path
import pytest

from batho.core.schemas import (
    PackageManager,
    PackageMetadata,
    SymbolRole,
    DescriptorSuffix,
    build_descriptor,
    generate_hierarchical_id,
    parse_hierarchical_id,
    Entity,
    EntityType,
    RelationshipType
)
from batho.modules.dependency.manifest_parser import ManifestParser
from batho.modules.extraction.submodules.parser_factory.factory import get_extractor


def detect_package_from_config(root_path):
    return ManifestParser.detect_project_metadata(root_path)


def test_package_metadata_serialization():
    meta = PackageMetadata(
        manager=PackageManager.PIP,
        name="test-pkg",
        version="1.2.3",
        source="https://github.com/user/test-pkg"
    )
    assert str(meta) == "pip test-pkg 1.2.3"
    
    d = meta.to_dict()
    assert d == {
        "manager": "pip",
        "name": "test-pkg",
        "version": "1.2.3",
        "source": "https://github.com/user/test-pkg"
    }
    
    meta2 = PackageMetadata.from_dict(d)
    assert meta2 == meta


def test_package_detector():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        
        # Test None when no config
        assert detect_package_from_config(root) is None
        
        # 1. Test NPM
        (root / "package.json").write_text('{"name": "my-npm-app", "version": "2.0.1"}', encoding="utf-8")
        meta = detect_package_from_config(root)
        assert meta is not None
        assert meta.manager == PackageManager.NPM
        assert meta.name == "my-npm-app"
        assert meta.version == "2.0.1"
        (root / "package.json").unlink()
        
        # 2. Test Poetry
        (root / "pyproject.toml").write_text(
            "[tool.poetry]\nname = \"my-poetry-app\"\nversion = \"3.4.0\"\n", encoding="utf-8"
        )
        meta = detect_package_from_config(root)
        assert meta is not None
        assert meta.manager == PackageManager.PIP
        assert meta.name == "my-poetry-app"
        assert meta.version == "3.4.0"
        (root / "pyproject.toml").unlink()
        
        # 3. Test Cargo
        (root / "Cargo.toml").write_text(
            "[package]\nname = \"my-cargo-app\"\nversion = \"0.1.2\"\n", encoding="utf-8"
        )
        meta = detect_package_from_config(root)
        assert meta is not None
        assert meta.manager == PackageManager.CARGO
        assert meta.name == "my-cargo-app"
        assert meta.version == "0.1.2"
        (root / "Cargo.toml").unlink()
        
        # 4. Test Go
        (root / "go.mod").write_text(
            "module github.com/user/my-go-app\ngo 1.22\n", encoding="utf-8"
        )
        meta = detect_package_from_config(root)
        assert meta is not None
        assert meta.manager == PackageManager.GO
        assert meta.name == "github.com/user/my-go-app"
        assert meta.version == "1.22"
        (root / "go.mod").unlink()

        # 5. Test Maven
        (root / "pom.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
            '  <artifactId>my-maven-app</artifactId>\n'
            '  <version>1.5.0</version>\n'
            '</project>', encoding="utf-8"
        )
        meta = detect_package_from_config(root)
        assert meta is not None
        assert meta.manager == PackageManager.MAVEN
        assert meta.name == "my-maven-app"
        assert meta.version == "1.5.0"
        (root / "pom.xml").unlink()

        # 6. Test Gradle
        (root / "build.gradle").write_text("version = '4.2.1'\n", encoding="utf-8")
        (root / "settings.gradle").write_text("rootProject.name = 'my-gradle-app'\n", encoding="utf-8")
        meta = detect_package_from_config(root)
        assert meta is not None
        assert meta.manager == PackageManager.GRADLE
        assert meta.name == "my-gradle-app"
        assert meta.version == "4.2.1"


def test_symbol_role():
    role1 = SymbolRole.Definition
    assert role1.is_definition()
    assert not role1.is_reference()
    assert not role1.is_import()
    assert str(role1) == "Definition"
    
    role2 = SymbolRole.ReadAccess | SymbolRole.WriteAccess
    assert not role2.is_definition()
    assert role2.is_reference()
    assert str(role2) == "WriteAccess, ReadAccess"
    
    role3 = SymbolRole.Import | SymbolRole.Generated
    assert role3.is_import()
    assert str(role3) == "Import, Generated"


def test_descriptor_suffix():
    assert build_descriptor("my_var", DescriptorSuffix.TERM) == "my_var."
    assert build_descriptor("MyClass", DescriptorSuffix.TYPE) == "MyClass#"
    assert build_descriptor("my_func", DescriptorSuffix.METHOD) == "my_func()."
    assert build_descriptor("my_ns", DescriptorSuffix.NAMESPACE) == "my_ns/"
    
    with pytest.raises(ValueError):
        build_descriptor("", DescriptorSuffix.TERM)
        
    with pytest.raises(ValueError):
        build_descriptor("invalid-name", DescriptorSuffix.TERM)


def test_hierarchical_id_round_trip():
    pkg = PackageMetadata(
        manager=PackageManager.PIP,
        name="my_app",
        version="1.0.0"
    )
    descriptors = [
        ("utils", DescriptorSuffix.NAMESPACE),
        ("Database", DescriptorSuffix.TYPE),
        ("connect", DescriptorSuffix.METHOD)
    ]
    
    hid = generate_hierarchical_id(pkg, descriptors)
    assert hid == "batho pip my_app 1.0.0 utils/Database#connect()."
    
    parsed_pkg, parsed_descriptors = parse_hierarchical_id(hid)
    assert parsed_pkg is not None
    assert parsed_pkg.manager == pkg.manager
    assert parsed_pkg.name == pkg.name
    assert parsed_pkg.version == pkg.version
    
    assert len(parsed_descriptors) == len(descriptors)
    for (n1, s1), (n2, s2) in zip(parsed_descriptors, descriptors):
        assert n1 == n2
        assert s1 == s2

    # Test without package
    hid_local = generate_hierarchical_id(None, [("main", DescriptorSuffix.TERM)])
    assert hid_local == "batho local project 0.0.0 main."
    parsed_pkg_local, parsed_desc_local = parse_hierarchical_id(hid_local)
    assert parsed_pkg_local is None or parsed_pkg_local.manager == PackageManager.UNKNOWN or parsed_pkg_local.name == "local"
    assert parsed_desc_local == [("main", DescriptorSuffix.TERM)]


def test_enclosing_range_python():
    extractor = get_extractor("python")
    assert extractor is not None
    
    content = b"""
@decorator
class MyClass:
    \"\"\"Docstring.\"\"\"
    def my_method(self):
        x = 42
        return x
"""
    entities, relationships = extractor.parse_file("test.py", content)
    
    # Check Class MyClass
    cls_ent = next(e for e in entities if e.type == EntityType.CLASS)
    assert cls_ent.enclosing_start_byte == content.find(b"@decorator")
    assert cls_ent.enclosing_end_byte >= content.find(b"return x")
    
    # Check method my_method
    method_ent = next(e for e in entities if e.type == EntityType.METHOD)
    assert method_ent.enclosing_start_byte == content.find(b"def my_method")
    assert method_ent.enclosing_end_byte == content.find(b"return x") + len(b"return x")
    
    # Check docstring entities
    doc_ents = [e for e in entities if e.is_documentation]
    assert len(doc_ents) == 1
    assert doc_ents[0].type == EntityType.COMMENT_BLOCK
    assert doc_ents[0].parent_id == cls_ent.id
    
    # Check if CONTAINS relationship is established
    contains_rel = next(
        (r for r in relationships if r.source_id == cls_ent.id and r.target_id == doc_ents[0].id),
        None
    )
    assert contains_rel is not None
    assert contains_rel.type == RelationshipType.CONTAINS


def test_read_write_states_python():
    extractor = get_extractor("python")
    assert extractor is not None
    
    content = b"""
def test_func():
    a = 1
    b = a + 2
    a += 1
"""
    entities, relationships = extractor.parse_file("test.py", content)
    
    # Verify relationships have roles (check r.roles field, not metadata)
    write_rels = [
        r for r in relationships 
        if r.roles & SymbolRole.WriteAccess
    ]
    read_rels = [
        r for r in relationships 
        if r.roles & SymbolRole.ReadAccess
    ]
    
    # 'a' in 'a = 1' and 'a += 1' is write
    assert len(write_rels) >= 1
    # 'a' in 'b = a + 2' is read
    assert len(read_rels) >= 1


def test_read_write_states_javascript():
    extractor = get_extractor("javascript")
    assert extractor is not None
    
    content = b"""
function testFunc() {
    let x = 1;
    let y = x + 2;
    x = 3;
}
"""
    entities, relationships = extractor.parse_file("test.js", content)
    
    write_rels = [
        r for r in relationships 
        if r.roles & SymbolRole.WriteAccess
    ]
    read_rels = [
        r for r in relationships 
        if r.roles & SymbolRole.ReadAccess
    ]
    
    assert len(write_rels) >= 1
    assert len(read_rels) >= 1

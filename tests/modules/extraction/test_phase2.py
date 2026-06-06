import os
import tempfile
from pathlib import Path
import pytest

from batho.core.schemas import (
    PackageManager,
    PackageMetadata,
    DescriptorSuffix,
    SymbolRole,
    Entity,
    EntityType,
    RelationshipType,
    generate_hierarchical_id,
)
from batho.modules.extraction.scope_manager import ScopeManager
from batho.modules.extraction.symbol_table import FileSymbolTable, SymbolDefinition, ImportStatement
from batho.modules.extraction.extractor import ASTExtractor
from batho.modules.graph.builder.codegraph import CodeGraphIndexer


def test_scope_manager_basic():
    sm = ScopeManager()
    
    # Test local scopes pushing and popping
    assert sm.get_current_scope() == ""
    
    p1 = sm.push_scope("MyClass", "class")
    assert p1 == "MyClass"
    assert sm.get_current_scope() == "MyClass"
    
    p2 = sm.push_scope("my_method", "method")
    assert p2 == "MyClass/my_method"
    assert sm.get_current_scope() == "MyClass/my_method"
    
    popped = sm.pop_scope()
    assert popped == "MyClass/my_method"
    assert sm.get_current_scope() == "MyClass"
    
    popped = sm.pop_scope()
    assert popped == "MyClass"
    assert sm.get_current_scope() == ""


def test_scope_manager_resolution():
    sm = ScopeManager()
    
    # 1. Define global symbol
    # Format of symbol_id should start with "batho "
    symbol_id_global = "batho local project 0.0.0 utils/Database#"
    sm.define_symbol("Database", symbol_id_global, "class", is_global=True)
    
    # 2. Define local symbol
    sm.push_scope("MyClass", "class")
    symbol_id_local = "batho local project 0.0.0 app/MyClass#local_var."
    sm.define_symbol("local_var", symbol_id_local, "variable", is_global=False)
    
    # 3. Resolve local
    info = sm.resolve_symbol("local_var")
    assert info is not None
    assert info.symbol_id == symbol_id_local
    assert info.symbol_type == "variable"
    assert info.is_external is False
    assert info.is_heuristic is False
    
    # 4. Resolve global
    info = sm.resolve_symbol("Database")
    assert info is not None
    assert info.symbol_id == symbol_id_global
    assert info.symbol_type == "class"
    assert info.is_external is False
    
    # 5. Shadowing test
    symbol_id_shadow = "batho local project 0.0.0 app/MyClass#Database."
    sm.define_symbol("Database", symbol_id_shadow, "variable", is_global=False)
    info = sm.resolve_symbol("Database")
    assert info is not None
    assert info.symbol_id == symbol_id_shadow
    assert info.symbol_type == "variable"
    
    # Exit scope
    sm.pop_scope()
    
    # Database resolves back to global
    info = sm.resolve_symbol("Database")
    assert info is not None
    assert info.symbol_id == symbol_id_global



def test_file_symbol_table_serialization():
    pkg = PackageMetadata(
        manager=PackageManager.PIP,
        name="my_app",
        version="1.0.0"
    )
    defn = SymbolDefinition(
        name="connect",
        symbol_type="method",
        start_byte=10,
        end_byte=50,
        enclosing_scope="Database",
        descriptor_chain=[("utils", DescriptorSuffix.NAMESPACE), ("Database", DescriptorSuffix.TYPE), ("connect", DescriptorSuffix.METHOD)],
        is_exported=True
    )
    imp = ImportStatement(
        module_path="utils",
        imported_names=["Database"],
        is_from_import=True,
        start_byte=0,
        end_byte=20
    )
    
    fst = FileSymbolTable(
        file_path=Path("main.py"),
        symbols={"connect": defn},
        imports=[imp],
        package=pkg
    )
    
    serialized = fst.to_dict()
    assert serialized["file_path"] == "main.py"
    assert "symbols" in serialized
    assert "imports" in serialized
    
    deserialized = FileSymbolTable.from_dict(serialized)
    assert deserialized.file_path == Path("main.py")
    assert "connect" in deserialized.symbols
    assert deserialized.symbols["connect"].name == "connect"
    assert deserialized.symbols["connect"].descriptor_chain == defn.descriptor_chain
    assert len(deserialized.imports) == 1
    assert deserialized.imports[0].module_path == "utils"
    assert deserialized.package == pkg


def test_dual_pass_indexing():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        
        # Create a Python file structure
        # utils.py
        utils_content = """
class Database:
    def connect(self):
        pass
"""
        # main.py
        main_content = """
from utils import Database

def run():
    db = Database()
    db.connect()
"""
        (root / "utils.py").write_text(utils_content, encoding="utf-8")
        (root / "main.py").write_text(main_content, encoding="utf-8")
        
        db_path = root / "test_db.batho"
        
        with CodeGraphIndexer(cache_path=str(db_path), root=str(root)) as indexer:
            graph = indexer.build_graph(
                root=str(root),
                max_workers=1,
                verbose=True,
                index_id="run-1",
                ast_cache_enabled=False,
                include_gaps=True,
            )
            
            # Verifications
            # 1. Check entities are generated
            entities = list(graph.entities.values())
            # We expect Database class and connect method to be defined
            db_classes = [e for e in entities if e.name == "Database" and e.type == EntityType.CLASS]
            assert len(db_classes) >= 1
            db_class = db_classes[0]
            
            # Hierarchical ID checks
            assert db_class.id.startswith("batho ")
            assert "utils/Database#" in db_class.id
            
            # Check connect method
            connect_methods = [e for e in entities if "Database.connect" in e.name and e.type == EntityType.METHOD]
            assert len(connect_methods) >= 1
            connect_method = connect_methods[0]
            assert "utils/Database#connect" in connect_method.id
            
            # Verify relationships
            relationships = graph.relationships
            print("RELATIONSHIPS:")
            for r in relationships:
                print(f"  {r.source_id} --({r.type.name})--> {r.target_id}")
            print("CONNECT METHOD ID:", connect_method.id)
            calls_rels = [r for r in relationships if r.type == RelationshipType.CALLS]
            assert len(calls_rels) >= 2
            
            # Find the CALLS relationship pointing to Database class
            resolved_class_calls = [r for r in calls_rels if r.target_id == db_class.id]
            assert len(resolved_class_calls) >= 1

            # Find the CALLS relationship pointing to the unresolved connect symbol
            # In the single-pass architecture, cross-file references emit contextual stubs
            # with format: "unresolved:<caller_scope>::<target_name>"
            resolved_connect_calls = [r for r in calls_rels if "connect" in r.target_id]
            assert len(resolved_connect_calls) >= 1
            ext_target_id = resolved_connect_calls[0].target_id

            # Verify that the target entity was generated as an UNRESOLVED contextual stub
            assert ext_target_id in graph.entities
            ext_entity = graph.entities[ext_target_id]
            assert ext_entity.type == EntityType.UNRESOLVED
            # Stub ID format: "unresolved:<caller_scope>::<target_name>"
            assert ext_entity.id.startswith("unresolved:")
            assert "connect" in ext_entity.id


def test_scope_manager_strict_resolution():
    # Strict resolver only
    sm = ScopeManager()
    symbol_id = "batho local project 0.0.0 app/StateChecker#test_state_checker_passed()."
    sm.define_symbol("test_state_checker_passed", symbol_id, "function", is_global=True)
    
    # Try resolving exact name
    info = sm.resolve_symbol_strict("test_state_checker_passed")
    assert info is not None
    assert info.symbol_id == symbol_id
    
    # Try resolving a typo/fuzzy name, should return None
    info = sm.resolve_symbol_strict("checker")
    assert info is None

    # Try resolving short name / ignored name, should return None
    info = sm.resolve_symbol_strict("self")
    assert info is None


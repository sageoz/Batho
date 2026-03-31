"""Tests for Objective-C extractor."""
from __future__ import annotations

import pytest

from batho_core.context.languages.registry import get_extractor, get_extractor_for_language
from batho_core.context.schema import EntityType


class TestObjectiveCExtractorRegistry:
    """Test Objective-C in the language registry."""

    def test_get_extractor_m_extension(self):
        ext = get_extractor(".m")
        assert ext is not None

    def test_get_extractor_mm_extension(self):
        ext = get_extractor(".mm")
        assert ext is not None

    def test_get_extractor_for_language(self):
        ext = get_extractor_for_language("objectivec")
        assert ext is not None

    def test_extractor_language_name(self):
        ext = get_extractor(".m")
        assert ext is not None
        assert ext._language_name == "objc"


class TestObjectiveCExtractorParsing:
    """Test Objective-C extractor parsing capabilities."""

    @staticmethod
    def _extractor_or_skip():
        ext = get_extractor(".m")
        if ext is None:
            pytest.skip("Objective-C extractor not available")
        return ext

    @staticmethod
    def _entity_by_name(entities, name: str):
        return next((e for e in entities if e.name == name), None)

    def test_extracts_interface_declaration(self):
        ext = self._extractor_or_skip()
        content = b"""
@interface MyClass : NSObject
@end
"""
        entities, _ = ext.parse_file("test.m", content)
        names = [e.name for e in entities]
        assert "MyClass" in names
        my_class = self._entity_by_name(entities, "MyClass")
        assert my_class is not None
        assert my_class.metadata.get("extends") == "NSObject"

    def test_extracts_implementation(self):
        ext = self._extractor_or_skip()
        content = b"""
@implementation MyClass
@end
"""
        entities, _ = ext.parse_file("test.m", content)
        names = [e.name for e in entities]
        assert "MyClass" in names

    def test_extracts_protocol(self):
        ext = self._extractor_or_skip()
        content = b"""
@protocol MyProtocol
@end
"""
        entities, _ = ext.parse_file("test.m", content)
        names = [e.name for e in entities]
        assert "MyProtocol" in names

    def test_extracts_methods_with_metadata(self):
        ext = self._extractor_or_skip()
        content = b"""
@interface MyClass
- (void)doSomething;
+ (instancetype)shared;
@end
"""
        entities, _ = ext.parse_file("test.m", content)
        method_entities = [e for e in entities if e.type == EntityType.METHOD]
        method_names = [e.name for e in method_entities]
        assert "doSomething" in method_names
        assert "shared" in method_names

        do_something = self._entity_by_name(method_entities, "doSomething")
        assert do_something is not None
        assert do_something.metadata.get("receiver") == "-"
        assert do_something.signature is not None
        assert "->" in do_something.signature

        shared = self._entity_by_name(method_entities, "shared")
        assert shared is not None
        assert shared.metadata.get("receiver") == "+"

    def test_extracts_property(self):
        ext = self._extractor_or_skip()
        content = b"""
@interface MyClass : NSObject
@property (nonatomic, strong) NSString *name;
@end
"""
        entities, _ = ext.parse_file("test.m", content)
        names = [e.name for e in entities]
        assert "MyClass" in names

        field = self._entity_by_name(entities, "name")
        assert field is not None
        assert field.type == EntityType.FIELD
        assert field.metadata.get("field_type") == "NSString"
        assert "strong" in field.metadata.get("visibility", "")

    def test_extracts_import(self):
        ext = self._extractor_or_skip()
        content = b"""
#import <Foundation/Foundation.h>
#import "Local.h"

@interface MyClass
@end
"""
        _, rels = ext.parse_file("test.m", content)
        import_rels = [r for r in rels if r.type.name == "IMPORTS"]
        assert len(import_rels) >= 2

    def test_extracts_category_and_extension_details(self):
        ext = self._extractor_or_skip()
        content = b"""
@interface NSString (MyCategory)
@end

@interface MyClass ()
@end
"""
        entities, _ = ext.parse_file("test.m", content)

        category = self._entity_by_name(entities, "MyCategory")
        assert category is not None
        assert category.type == EntityType.INTERFACE
        assert category.metadata.get("extends") == "NSString"

        extension = self._entity_by_name(entities, "MyClass")
        assert extension is not None
        assert extension.type in (EntityType.CLASS, EntityType.INTERFACE)

    def test_extracts_protocol_implementation_relationships(self):
        ext = self._extractor_or_skip()
        content = b"""
@protocol P1
@end

@protocol P2
@end

@interface MyClass : NSObject <P1, P2>
@end
"""
        entities, rels = ext.parse_file("test.m", content)
        names = [e.name for e in entities]
        assert "MyClass" in names
        assert "P1" in names
        assert "P2" in names

        implements = [r for r in rels if r.type.name == "IMPLEMENTS"]
        assert len(implements) >= 1

    def test_extracts_protocol_inheritance_relationship(self):
        ext = self._extractor_or_skip()
        content = b"""
@protocol P1
@end

@protocol P2 <P1>
@end
"""
        entities, rels = ext.parse_file("test.m", content)
        names = [e.name for e in entities]
        assert "P2" in names
        assert "P1" in names

        implements = [r for r in rels if r.type.name == "IMPLEMENTS"]
        assert len(implements) >= 1

    def test_extracts_selector_call_relationship(self):
        ext = self._extractor_or_skip()
        content = b"""
@interface MyClass
- (void)doThing;
- (void)run;
@end

@implementation MyClass
- (void)doThing {
}

- (void)run {
    [self doThing];
}
@end
"""
        _, rels = ext.parse_file("test.m", content)
        calls = [r for r in rels if r.type.name == "CALLS"]
        assert len(calls) >= 1

    def test_full_class_with_methods(self):
        ext = self._extractor_or_skip()
        content = b"""
#import <Foundation/Foundation.h>

@protocol Greeter
- (NSString *)greet:(NSString *)name;
@end

@interface Person : NSObject
- (NSString *)greet:(NSString *)name;
@property (nonatomic, assign) NSInteger age;
@end

@implementation Person
- (NSString *)greet:(NSString *)name {
    return [NSString stringWithFormat:@"Hello, %@", name];
}
@end
"""
        entities, rels = ext.parse_file("Person.m", content)
        names = [e.name for e in entities]
        assert "Person" in names
        assert "age" in names
        assert "greet" in names

        inherits = [r for r in rels if r.type.name == "INHERITS"]
        imports = [r for r in rels if r.type.name == "IMPORTS"]
        assert len(inherits) >= 1
        assert len(imports) >= 1

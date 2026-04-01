# Frozen Graph Format Specification (.sageoz_graph)

## Overview

The `.sageoz_graph` format stores pre-computed, immutable context graphs that combine Tree-sitter AST data with LSP semantic analysis. This format enables:

- **Deterministic Reproducibility**: Identical graphs across runs
- **Fast Agent Loading**: LLM agents read pre-computed graphs without LSP overhead
- **Audit Compliance**: Cryptographic verification of graph integrity
- **Version Control**: Graphs tagged to specific code commits

---

## Design Goals

1. **Immutable**: Once written, never modified (new versions for changes)
2. **Compact**: Compressed binary format for efficient storage
3. **Fast**: Memory-mappable, minimal deserialization overhead
4. **Verifiable**: Embedded Merkle tree root for integrity checks
5. **Extensible**: Forward-compatible format for future enhancements

---

## File Format (Binary)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        .sageoz_graph File Layout                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                     Header (128 bytes)                        │   │
│  │  • Magic: "SAGE" (4 bytes)                                   │   │
│  │  • Version: uint32 (4 bytes)                                 │   │
│  │  • Format: uint8 (1 byte) - compression type                 │   │
│  │  • Flags: uint8 (1 byte)                                     │   │
│  │  • Reserved: 118 bytes                                       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                  Metadata Section (Variable)                  │   │
│  │  • Graph metadata (JSON, compressed)                         │   │
│  │    - Creation timestamp                                      │   │
│  │    - Source commit SHA                                       │   │
│  │    - LSP versions used                                       │   │
│  │    - File count                                              │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                  Merkle Tree Section (Variable)               │   │
│  │  • Merkle tree root hash (32 bytes SHA256)                   │   │
│  │  • Tree structure (optional, for verification)               │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                   Graph Data Section (Variable)               │   │
│  │  • Compressed node data (zstd/lz4)                           │   │
│  │  • Node index for fast lookups                               │   │
│  │  • Edge list                                                 │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                  String Table (Variable)                      │   │
│  │  • Deduplicated strings (paths, identifiers, etc.)             │   │
│  │  • Referenced by offset in node data                         │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                     Footer (32 bytes)                         │   │
│  │  • Data section CRC32 (4 bytes)                              │   │
│  │  • Total file size (8 bytes)                                 │   │
│  │  • Section offsets array (16 bytes)                          │   │
│  │  • Magic: "EOFS" (4 bytes)                                   │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Header Format (128 bytes)

```c
struct GraphHeader {
    // Magic identifier
    uint8_t magic[4];           // "SAGE"
    
    // Format version (semantic versioning as uint32)
    // Major.Minor.Patch -> (major << 16) | (minor << 8) | patch
    uint32_t version;           // e.g., 0x00010000 = v1.0.0
    
    // Compression algorithm
    uint8_t compression;        // 0=none, 1=zstd, 2=lz4, 3=snappy
    
    // Feature flags
    uint8_t flags;              // Bitfield:
                                // bit 0: has_merkle_tree
                                // bit 1: has_type_info
                                // bit 2: has_call_graph
                                // bit 3: has_lsp_data
                                // bits 4-7: reserved
    
    // Reserved for future use
    uint8_t reserved[118];
};
```

---

## Node Structure

### Base Node

```c
struct GraphNode {
    // Node identification
    uint32_t node_id;           // Unique node identifier
    uint8_t node_type;          // Node type enum (see below)
    uint8_t language;           // Language identifier (see registry)
    
    // Source location
    uint32_t file_id;           // Index into file table
    uint32_t start_line;        // 0-indexed
    uint32_t start_column;      // 0-indexed, UTF-8 bytes
    uint32_t end_line;
    uint32_t end_column;
    
    // LSP data hash (for audit trail)
    uint8_t lsp_hash[32];       // SHA256 of LSP response (if applicable)
    
    // String references (offsets into string table)
    uint32_t name_offset;       // Symbol name
    uint32_t type_offset;       // Type signature (if known)
    uint32_t doc_offset;        // Documentation (optional)
    
    // Relationships
    uint32_t parent_id;         // Parent node (0 if root)
    uint32_t child_count;       // Number of children
    uint32_t children_offset;   // Offset into child index
    
    // Cross-file references (for definition resolution)
    uint32_t definition_count;  // Number of definitions
    uint32_t definitions_offset;// Offset into definition table
    uint32_t reference_count;   // Number of references
    uint32_t references_offset; // Offset into reference table
    
    // Type information (if available)
    uint8_t type_kind;          // Type kind enum
    uint32_t type_node_id;      // Reference to type definition node
};
```

### Node Types

```python
class NodeType(IntEnum):
    # Container types
    FILE = 1           # Source file
    MODULE = 2         # Module/package
    NAMESPACE = 3      # Namespace
    
    # Type definitions
    CLASS = 10         # Class definition
    INTERFACE = 11     # Interface definition
    ENUM = 12          # Enum definition
    STRUCT = 13        # Struct definition
    TYPEDEF = 14       # Type alias/typedef
    
    # Callables
    FUNCTION = 20      # Function definition
    METHOD = 21        # Method definition
    CONSTRUCTOR = 22   # Constructor
    LAMBDA = 23        # Lambda/anonymous function
    
    # Variables
    VARIABLE = 30      # Variable declaration
    CONSTANT = 31      # Constant declaration
    PARAMETER = 32     # Function parameter
    FIELD = 33         # Object field
    PROPERTY = 34      # Property (getter/setter)
    
    # Statements
    BLOCK = 40         # Code block
    IF = 41            # If statement
    LOOP = 42          # Loop (for, while, etc.)
    TRY = 43           # Try/catch
    
    # Expressions
    CALL = 50          # Function/method call
    REFERENCE = 51     # Symbol reference
    LITERAL = 52       # Literal value
    BINARY_OP = 53     # Binary operation
    UNARY_OP = 54      # Unary operation
    
    # Special
    IMPORT = 60        # Import/using statement
    EXPORT = 61        # Export statement
    ANNOTATION = 62    # Decorator/annotation
    COMMENT = 63       # Comment node
    
    # LSP-specific
    TYPE_INFO = 70     # LSP type information
    DIAGNOSTIC = 71    # LSP diagnostic
```

### Type Kinds

```python
class TypeKind(IntEnum):
    UNKNOWN = 0
    PRIMITIVE = 1      # int, string, bool, etc.
    CUSTOM = 2         # User-defined type
    GENERIC = 3        # Generic type with parameters
    FUNCTION = 4       # Function type
    UNION = 5          # Union type (A | B)
    INTERSECTION = 6   # Intersection type (A & B)
    ARRAY = 7          # Array/Slice type
    MAP = 8            # Map/Dict type
    OPTIONAL = 9       # Optional/Nullable type
    POINTER = 10       # Pointer/Reference type
    TUPLE = 11         # Tuple type
```

---

## String Table

Deduplicated string storage for efficient memory usage.

```c
struct StringTable {
    uint32_t count;             // Number of strings
    uint32_t total_bytes;      // Total string data size
    
    // Offset table (count entries)
    uint32_t offsets[count];   // Offset of each string in data
    
    // String data (UTF-8, null-terminated)
    uint8_t data[total_bytes];
};
```

---

## Edge Structure

```c
struct GraphEdge {
    uint32_t source_id;         // Source node ID
    uint32_t target_id;         // Target node ID
    uint8_t edge_type;          // Edge type enum
    uint32_t weight;            // Optional weight (for call frequency)
};

enum EdgeType {
    CONTAINS = 1,       // Parent-child relationship
    DEFINES = 2,        // Definition relationship
    REFERENCES = 3,     // Symbol reference
    CALLS = 4,          // Function call
    INHERITS = 5,       // Inheritance
    IMPLEMENTS = 6,     // Interface implementation
    IMPORTS = 7,        // Import/using
    EXPORTS = 8,        // Export
    TYPE_OF = 9,        // Type relationship
    DEPENDS_ON = 10,    // Dependency
};
```

---

## Python Implementation

### Serializer

```python
# batho_core/graph/serializer.py

import struct
import hashlib
import zstandard as zstd
from dataclasses import dataclass
from typing import List, Dict, Optional, BinaryIO
from enum import IntEnum
import json

class GraphSerializer:
    """
    Serializes InMemoryGraph to .sageoz_graph format.
    """
    
    FORMAT_VERSION = 0x00010000  # v1.0.0
    MAGIC_HEADER = b"SAGE"
    MAGIC_FOOTER = b"EOFS"
    
    def __init__(self, compression: str = "zstd", level: int = 3):
        self.compression = compression
        self.level = level
        
    def serialize(
        self,
        graph: 'InMemoryGraph',
        metadata: GraphMetadata,
        merkle_root: str,
        output: BinaryIO
    ) -> int:
        """
        Serialize graph to binary format.
        
        Args:
            graph: InMemoryGraph to serialize
            metadata: Creation metadata
            merkle_root: Merkle tree root hash
            output: Binary output stream
            
        Returns:
            Total bytes written
        """
        # Build string table
        string_table = self._build_string_table(graph)
        
        # Serialize nodes
        node_data = self._serialize_nodes(graph, string_table)
        
        # Serialize edges
        edge_data = self._serialize_edges(graph)
        
        # Serialize metadata
        metadata_bytes = json.dumps(metadata.to_dict()).encode('utf-8')
        
        # Compress data sections
        compressed_nodes = self._compress(node_data)
        compressed_edges = self._compress(edge_data)
        compressed_metadata = self._compress(metadata_bytes)
        
        # Write header
        header = self._make_header(
            has_merkle=True,
            has_types=metadata.has_type_info,
            has_calls=metadata.has_call_graph,
            has_lsp=metadata.has_lsp_data
        )
        output.write(header)
        
        # Calculate section offsets
        metadata_offset = 128  # After header
        merkle_offset = metadata_offset + len(compressed_metadata) + 4
        nodes_offset = merkle_offset + 32 + 4  # root hash + length
        edges_offset = nodes_offset + len(compressed_nodes) + 4
        strings_offset = edges_offset + len(compressed_edges) + 4
        
        # Write metadata section
        output.write(struct.pack('<I', len(compressed_metadata)))
        output.write(compressed_metadata)
        
        # Write Merkle section
        output.write(struct.pack('<I', 32))  # root hash size
        output.write(bytes.fromhex(merkle_root))
        
        # Write nodes section
        output.write(struct.pack('<I', len(compressed_nodes)))
        output.write(compressed_nodes)
        
        # Write edges section
        output.write(struct.pack('<I', len(compressed_edges)))
        output.write(compressed_edges)
        
        # Write string table
        string_data = self._serialize_string_table(string_table)
        compressed_strings = self._compress(string_data)
        output.write(struct.pack('<I', len(compressed_strings)))
        output.write(compressed_strings)
        
        # Calculate file size
        file_size = output.tell()
        
        # Write footer
        data_crc = self._calculate_crc(
            compressed_nodes + compressed_edges + compressed_strings
        )
        self._write_footer(output, data_crc, file_size, [
            metadata_offset, merkle_offset, nodes_offset, edges_offset, strings_offset
        ])
        
        return file_size
        
    def _make_header(
        self,
        has_merkle: bool,
        has_types: bool,
        has_calls: bool,
        has_lsp: bool
    ) -> bytes:
        """Create file header."""
        flags = 0
        if has_merkle:
            flags |= 0x01
        if has_types:
            flags |= 0x02
        if has_calls:
            flags |= 0x04
        if has_lsp:
            flags |= 0x08
            
        compression_code = {"none": 0, "zstd": 1, "lz4": 2}.get(
            self.compression, 1
        )
        
        header = struct.pack(
            '<4sI BB',
            self.MAGIC_HEADER,
            self.FORMAT_VERSION,
            compression_code,
            flags
        )
        
        # Pad to 128 bytes
        header += b'\x00' * (128 - len(header))
        
        return header
        
    def _compress(self, data: bytes) -> bytes:
        """Compress data using configured algorithm."""
        if self.compression == "zstd":
            cctx = zstd.ZstdCompressor(level=self.level)
            return cctx.compress(data)
        elif self.compression == "lz4":
            import lz4.frame
            return lz4.frame.compress(data, compression_level=self.level)
        elif self.compression == "none":
            return data
        else:
            raise ValueError(f"Unknown compression: {self.compression}")
            
    def _build_string_table(self, graph: 'InMemoryGraph') -> Dict[str, int]:
        """Build deduplicated string table."""
        strings = set()
        
        for node in graph.nodes:
            if node.name:
                strings.add(node.name)
            if node.type_signature:
                strings.add(node.type_signature)
            if node.documentation:
                strings.add(node.documentation)
            if node.file_path:
                strings.add(str(node.file_path))
                
        # Sort for deterministic ordering
        sorted_strings = sorted(strings)
        
        # Build offset map
        table = {}
        offset = 0
        for s in sorted_strings:
            table[s] = offset
            offset += len(s.encode('utf-8')) + 1  # +1 for null terminator
            
        return table
        
    def _serialize_nodes(
        self,
        graph: 'InMemoryGraph',
        string_table: Dict[str, int]
    ) -> bytes:
        """Serialize node data."""
        data = bytearray()
        
        for node in graph.nodes:
            node_bytes = struct.pack(
                '<I B B',           # id, type, language
                node.id,
                node.node_type.value,
                node.language.value
            )
            
            # Source location
            node_bytes += struct.pack(
                '<I IIII',
                node.file_id,
                node.start_line,
                node.start_column,
                node.end_line,
                node.end_column
            )
            
            # LSP hash
            node_bytes += bytes.fromhex(node.lsp_hash) if node.lsp_hash else b'\x00' * 32
            
            # String references
            node_bytes += struct.pack(
                '<III',
                string_table.get(node.name, 0),
                string_table.get(node.type_signature, 0),
                string_table.get(node.documentation, 0)
            )
            
            # Relationships
            node_bytes += struct.pack(
                '<IIIIII',
                node.parent_id or 0,
                len(node.children),
                0,  # children_offset (filled in later)
                len(node.definitions),
                0,  # definitions_offset
                len(node.references)
            )
            
            data.extend(node_bytes)
            
        return bytes(data)
        
    def _write_footer(
        self,
        output: BinaryIO,
        crc: int,
        file_size: int,
        section_offsets: List[int]
    ) -> None:
        """Write file footer."""
        footer = struct.pack('<I', crc)           # CRC32
        footer += struct.pack('<Q', file_size)     # File size
        
        # Section offsets (max 4 offsets in 16 bytes)
        for offset in section_offsets[:4]:
            footer += struct.pack('<I', offset)
        footer += b'\x00' * (16 - len(section_offsets) * 4)
        
        footer += self.MAGIC_FOOTER
        
        output.write(footer)
```

### Deserializer

```python
class GraphDeserializer:
    """
    Deserializes .sageoz_graph files to InMemoryGraph.
    """
    
    def __init__(self, mmap: bool = True):
        self.mmap = mmap
        
    def deserialize(self, input_path: str) -> FrozenGraph:
        """
        Deserialize graph from file.
        
        Args:
            input_path: Path to .sageoz_graph file
            
        Returns:
            FrozenGraph with metadata and access to nodes
        """
        with open(input_path, 'rb') as f:
            # Read header
            header = f.read(128)
            magic, version, compression, flags = struct.unpack('<4sI BB', header[:10])
            
            if magic != b"SAGE":
                raise ValueError(f"Invalid file format: {magic}")
                
            # Read section offsets from footer
            f.seek(-32, 2)  # Go to footer
            footer = f.read(32)
            crc, file_size = struct.unpack('<IQ', footer[:12])
            section_offsets = list(struct.unpack('<IIII', footer[12:28]))
            footer_magic = footer[28:32]
            
            if footer_magic != b"EOFS":
                raise ValueError(f"Corrupt file: invalid footer")
                
            # Read and decompress sections
            f.seek(section_offsets[0])  # Metadata offset
            metadata = self._read_section(f, 'json')
            
            f.seek(section_offsets[1])  # Merkle offset
            merkle_root = self._read_merkle(f)
            
            f.seek(section_offsets[2])  # Nodes offset
            node_data = self._read_section(f, 'raw', compression)
            
            f.seek(section_offsets[3])  # Edges offset
            edge_data = self._read_section(f, 'raw', compression)
            
            # Parse nodes (lazy loading)
            nodes = LazyNodeList(node_data, offset=section_offsets[2])
            
            # Parse edges
            edges = self._parse_edges(edge_data)
            
            return FrozenGraph(
                metadata=GraphMetadata.from_dict(metadata),
                merkle_root=merkle_root,
                nodes=nodes,
                edges=edges,
                file_path=input_path
            )
            
    def _read_section(
        self,
        f: BinaryIO,
        data_type: str,
        compression: Optional[str] = None
    ) -> Any:
        """Read and decompress a section."""
        length = struct.unpack('<I', f.read(4))[0]
        compressed = f.read(length)
        
        if compression == "zstd":
            dctx = zstd.ZstdDecompressor()
            data = dctx.decompress(compressed)
        elif compression == "lz4":
            import lz4.frame
            data = lz4.frame.decompress(compressed)
        else:
            data = compressed
            
        if data_type == 'json':
            return json.loads(data.decode('utf-8'))
        else:
            return data
            
    def _read_merkle(self, f: BinaryIO) -> str:
        """Read Merkle root hash."""
        length = struct.unpack('<I', f.read(4))[0]
        return f.read(length).hex()
```

### Lazy Loading

```python
class LazyNodeList:
    """
    Memory-efficient lazy loading for large graphs.
    """
    
    def __init__(self, node_data: bytes, offset: int):
        self._data = node_data
        self._offset = offset
        self._node_count = len(node_data) // 64  # Approximate
        self._cache: Dict[int, GraphNode] = {}
        self._cache_size = 1000  # LRU cache size
        
    def __getitem__(self, index: int) -> GraphNode:
        """Get node by index (lazy load)."""
        if index in self._cache:
            return self._cache[index]
            
        node = self._load_node(index)
        self._cache[index] = node
        
        # Simple LRU: clear if too big
        if len(self._cache) > self._cache_size:
            self._cache.clear()
            self._cache[index] = node
            
        return node
        
    def __len__(self) -> int:
        return self._node_count
        
    def _load_node(self, index: int) -> GraphNode:
        """Load node from binary data."""
        # Calculate offset
        node_size = 64  # Approximate average
        offset = index * node_size
        
        # Parse binary data
        node_bytes = self._data[offset:offset + node_size]
        
        return GraphNode(
            id=struct.unpack('<I', node_bytes[0:4])[0],
            node_type=NodeType(node_bytes[4]),
            # ... parse remaining fields
        )
        
    def by_type(self, node_type: NodeType) -> Iterator[GraphNode]:
        """Iterate nodes of specific type."""
        for i in range(len(self)):
            node = self[i]
            if node.node_type == node_type:
                yield node
                
    def by_file(self, file_id: int) -> Iterator[GraphNode]:
        """Iterate nodes from specific file."""
        for i in range(len(self)):
            node = self[i]
            if node.file_id == file_id:
                yield node
```

---

## Cache Integration

### Graph Cache Key

```python
def compute_cache_key(
    project_path: str,
    commit_sha: str,
    config_hash: str
) -> str:
    """
    Compute deterministic cache key for frozen graph.
    
    Args:
        project_path: Absolute path to project
        commit_sha: Git commit SHA
        config_hash: Hash of Batho configuration
        
    Returns:
        SHA256 hex string for cache lookup
    """
    key_data = f"{project_path}:{commit_sha}:{config_hash}"
    return hashlib.sha256(key_data.encode()).hexdigest()
```

### Cache Storage

```python
class GraphCache:
    """
    Content-addressed cache for frozen graphs.
    """
    
    def __init__(self, cache_dir: str, max_size_gb: float = 10.0):
        self.cache_dir = Path(cache_dir)
        self.max_size = max_size_gb * 1024 * 1024 * 1024
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
    def get(self, key: str) -> Optional[Path]:
        """Get cached graph by key."""
        cache_file = self.cache_dir / f"{key}.sageoz_graph"
        if cache_file.exists():
            return cache_file
        return None
        
    def put(self, key: str, graph_path: str) -> Path:
        """Store graph in cache."""
        cache_file = self.cache_dir / f"{key}.sageoz_graph"
        
        # Copy or hardlink
        import shutil
        shutil.copy2(graph_path, cache_file)
        
        # Update metadata
        self._update_metadata(key, cache_file.stat().st_size)
        
        # Evict if needed
        self._evict_if_needed()
        
        return cache_file
        
    def _evict_if_needed(self):
        """Evict oldest entries if cache exceeds max size."""
        # LRU eviction based on access time
        # ... implementation
```

---

## Version Compatibility

### Forward Compatibility

- Unknown node types: Store but don't process
- Unknown fields: Preserve in binary data
- New compression: Detect and decompress

### Backward Compatibility (Not Supported)

Frozen graphs are immutable. Old format versions are not supported:
- Regenerate graph with new Batho version
- Clear cache when upgrading

---

## Performance Benchmarks

| Metric | Target | Notes |
|--------|--------|-------|
| Serialization | 50K nodes/sec | With zstd compression |
| Deserialization | 100K nodes/sec | Lazy loading |
| Memory (loaded) | 50 bytes/node | Excluding strings |
| File size | 30% of original | With compression |
| Random access | < 1ms | Cached node lookup |
| File integrity check | < 10ms | CRC + Merkle verify |

---

**Version**: 1.0.0  
**Format Status**: DRAFT  
**Last Updated**: 2026-03-31

# Batho LSP Client API Specification

## Overview

The Universal LSP Client provides a high-performance, async interface for communicating with language servers in hermetic containers. It handles JSON-RPC messaging, capability negotiation, response caching, and deterministic hashing.

---

## Core API

### LSPClient

```python
class LSPClient:
    """
    Universal LSP client for communicating with language servers.
    
    Manages LSP process lifecycle, JSON-RPC communication, and response handling.
    All methods are async and support timeout/retry logic.
    """
    
    def __init__(
        self,
        language: str,
        container_config: ContainerConfig,
        adapter: Optional[LSPAdapter] = None,
        cache: Optional[LSPCache] = None,
        timeout_ms: int = 30000,
        max_retries: int = 3
    ):
        """
        Initialize LSP client for a specific language.
        
        Args:
            language: Language identifier (e.g., 'python', 'typescript')
            container_config: Hermetic container configuration
            adapter: Language-specific LSP adapter (optional)
            cache: Response cache instance (optional)
            timeout_ms: Default timeout for LSP requests
            max_retries: Maximum retry attempts for failed requests
        """
        ...
    
    async def initialize(
        self,
        root_uri: str,
        capabilities: ClientCapabilities
    ) -> InitializeResult:
        """
        Initialize the LSP connection.
        
        Spawns the LSP process in hermetic container and performs
        capability negotiation.
        
        Args:
            root_uri: Project root URI (file://...)
            capabilities: Client capabilities to advertise
            
        Returns:
            InitializeResult with server capabilities
            
        Raises:
            LSPConnectionError: If LSP process fails to start
            LSPTimeoutError: If initialization times out
        """
        ...
    
    async def shutdown(self) -> None:
        """
        Gracefully shutdown LSP connection.
        
        Sends shutdown request, waits for response, then exits.
        """
        ...
    
    async def __aenter__(self) -> 'LSPClient':
        """Async context manager entry."""
        ...
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - ensures cleanup."""
        ...
```

---

## Text Document Methods

### Definition Resolution

```python
async def textDocument_definition(
    self,
    text_document: TextDocumentIdentifier,
    position: Position,
    timeout_ms: Optional[int] = None
) -> DefinitionResponse:
    """
    Resolve symbol definition location.
    
    Args:
        text_document: Document identifier with URI
        position: Cursor position (line, character)
        timeout_ms: Override default timeout
        
    Returns:
        DefinitionResponse containing:
        - locations: List of Location objects
        - hash: SHA256 of raw LSP response
        - raw: Raw JSON-RPC response (for debugging)
        
    Example:
        >>> response = await client.textDocument_definition(
        ...     TextDocumentIdentifier(uri="file:///src/main.py"),
        ...     Position(line=10, character=15)
        ... )
        >>> print(response.locations[0].uri)
        'file:///src/utils.py'
    """
    ...
```

### References Resolution

```python
async def textDocument_references(
    self,
    text_document: TextDocumentIdentifier,
    position: Position,
    context: ReferenceContext,
    timeout_ms: Optional[int] = None
) -> ReferencesResponse:
    """
    Find all references to a symbol.
    
    Used for call-chain analysis and cross-file dependencies.
    
    Args:
        text_document: Document identifier
        position: Symbol position
        context: Reference context (includeDeclaration, etc.)
        timeout_ms: Override default timeout
        
    Returns:
        ReferencesResponse containing:
        - locations: List of reference locations
        - hash: SHA256 of raw response
        - count: Total reference count
        
    Example:
        >>> context = ReferenceContext(include_declaration=True)
        >>> response = await client.textDocument_references(
        ...     doc, position, context
        ... )
        >>> for loc in response.locations:
        ...     print(f"Reference at {loc.uri}:{loc.range.start.line}")
    """
    ...
```

### Type Information

```python
async def textDocument_typeDefinition(
    self,
    text_document: TextDocumentIdentifier,
    position: Position,
    timeout_ms: Optional[int] = None
) -> TypeDefinitionResponse:
    """
    Resolve type definition for a symbol.
    
    Essential for type inference and generic analysis.
    """
    ...

async def textDocument_hover(
    self,
    text_document: TextDocumentIdentifier,
    position: Position,
    timeout_ms: Optional[int] = None
) -> HoverResponse:
    """
    Get hover information (type, docs) for a symbol.
    
    Returns:
        HoverResponse with:
        - contents: Type signature and documentation
        - range: Source range
        - hash: Response hash
    """
    ...
```

### Document Symbols

```python
async def textDocument_documentSymbol(
    self,
    text_document: TextDocumentIdentifier,
    timeout_ms: Optional[int] = None
) -> DocumentSymbolResponse:
    """
    Get all symbols defined in a document.
    
    Used for building symbol tables and navigation.
    
    Returns:
        DocumentSymbolResponse with hierarchical symbol tree:
        - symbols: List of DocumentSymbol (classes, functions, variables)
        - hash: Response hash
        
    Example:
        >>> response = await client.textDocument_documentSymbol(doc)
        >>> for symbol in response.symbols:
        ...     print(f"{symbol.kind.name}: {symbol.name}")
    """
    ...
```

---

## Workspace Methods

```python
async def workspace_symbol(
    self,
    query: str,
    timeout_ms: Optional[int] = None
) -> WorkspaceSymbolResponse:
    """
    Search symbols across entire workspace.
    
    Args:
        query: Symbol name or pattern
        timeout_ms: Override default timeout
        
    Returns:
        WorkspaceSymbolResponse with matching symbols
    """
    ...
```

---

## Batch Operations

```python
async def batch_resolve(
    self,
    requests: List[ResolutionRequest],
    max_parallel: int = 10,
    timeout_ms: Optional[int] = None
) -> BatchResponse:
    """
    Resolve multiple symbols in parallel.
    
    Critical for performance when processing large files.
    
    Args:
        requests: List of ResolutionRequest objects
        max_parallel: Maximum concurrent requests
        timeout_ms: Total batch timeout
        
    Returns:
        BatchResponse with:
        - results: Dict[request_id, ResolutionResult]
        - completed: Number of successful resolutions
        - failed: Number of failed resolutions
        - combined_hash: Hash of all responses (for determinism)
        
    Example:
        >>> requests = [
        ...     ResolutionRequest(doc1, pos1, "definition"),
        ...     ResolutionRequest(doc2, pos2, "references"),
        ... ]
        >>> response = await client.batch_resolve(requests, max_parallel=5)
        >>> print(f"Resolved {response.completed}/{len(requests)} symbols")
    """
    ...
```

---

## Data Structures

### TextDocumentIdentifier

```python
@dataclass
class TextDocumentIdentifier:
    """Identifies a text document by URI."""
    uri: str  # file://... or other valid URI
    
    @validator('uri')
    def validate_uri(cls, v):
        if not v.startswith(('file://', 'untitled://', 'inmemory://')):
            raise ValueError(f"Invalid URI scheme: {v}")
        return v
```

### Position

```python
@dataclass
class Position:
    """0-based position in a text document."""
    line: int      # 0-indexed line number
    character: int # 0-indexed character offset
    
    def __lt__(self, other: 'Position') -> bool:
        return (self.line, self.character) < (other.line, other.character)
```

### Range

```python
@dataclass
class Range:
    """Range of positions in a document."""
    start: Position
    end: Position
    
    def contains(self, position: Position) -> bool:
        return self.start <= position < self.end
```

### Location

```python
@dataclass
class Location:
    """Location of a symbol in a document."""
    uri: str
    range: Range
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'uri': self.uri,
            'range': {
                'start': {'line': self.range.start.line, 'character': self.range.start.character},
                'end': {'line': self.range.end.line, 'character': self.range.end.character}
            }
        }
```

### DocumentSymbol

```python
class SymbolKind(IntEnum):
    FILE = 1
    MODULE = 2
    NAMESPACE = 3
    PACKAGE = 4
    CLASS = 5
    METHOD = 6
    PROPERTY = 7
    FIELD = 8
    CONSTRUCTOR = 9
    ENUM = 10
    INTERFACE = 11
    FUNCTION = 12
    VARIABLE = 13
    CONSTANT = 14
    # ... (all LSP symbol kinds)

@dataclass
class DocumentSymbol:
    """Hierarchical symbol information."""
    name: str
    detail: Optional[str]  # Type signature, etc.
    kind: SymbolKind
    range: Range
    selection_range: Range  # Range to select when navigating
    children: List['DocumentSymbol']  # Nested symbols
    hash: str  # SHA256 of this symbol's LSP data
```

### Response Types

```python
@dataclass
class LSPResponse:
    """Base class for all LSP responses."""
    raw_json: str          # Raw JSON-RPC response
    hash: str              # SHA256 of raw_json
    timestamp: datetime    # When response received
    duration_ms: int       # Request duration
    
@dataclass  
class DefinitionResponse(LSPResponse):
    locations: List[Location]
    
@dataclass
class ReferencesResponse(LSPResponse):
    locations: List[Location]
    count: int
    
@dataclass
class HoverResponse(LSPResponse):
    contents: Union[str, Dict[str, Any]]  # Plain text or MarkupContent
    range: Optional[Range]
    
@dataclass
class DocumentSymbolResponse(LSPResponse):
    symbols: List[DocumentSymbol]
    
@dataclass
class BatchResponse:
    results: Dict[str, LSPResponse]
    combined_hash: str
    completed: int
    failed: int
    total_duration_ms: int
```

---

## Error Handling

### Exception Hierarchy

```python
class LSPError(Exception):
    """Base LSP error."""
    pass

class LSPConnectionError(LSPError):
    """Failed to connect to LSP process."""
    def __init__(self, language: str, cause: str):
        self.language = language
        self.cause = cause
        super().__init__(f"LSP connection failed for {language}: {cause}")

class LSPTimeoutError(LSPError):
    """LSP request timed out."""
    def __init__(self, method: str, timeout_ms: int):
        self.method = method
        self.timeout_ms = timeout_ms
        super().__init__(f"LSP method {method} timed out after {timeout_ms}ms")

class LSPResponseError(LSPError):
    """LSP server returned error response."""
    def __init__(self, code: int, message: str, data: Optional[Dict] = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"LSP error {code}: {message}")

class LSPNotInitializedError(LSPError):
    """Client used before initialization."""
    pass

class LSPProcessError(LSPError):
    """LSP process crashed or exited unexpectedly."""
    def __init__(self, return_code: int, stderr: str):
        self.return_code = return_code
        self.stderr = stderr
        super().__init__(f"LSP process exited with code {return_code}: {stderr}")
```

---

## Configuration

### ContainerConfig

```python
@dataclass
class ContainerConfig:
    """Configuration for hermetic LSP container."""
    
    # Container image specification
    image: str                    # e.g., "batho-lsp/python:latest"
    image_digest: str             # SHA256 of image
    
    # LSP binary within container
    lsp_command: List[str]        # e.g., ["pyright-langserver", "--stdio"]
    lsp_version: str              # e.g., "1.1.350"
    lsp_binary_sha256: str        # SHA256 of LSP binary
    
    # Resource limits
    memory_limit_mb: int = 2048
    cpu_limit: float = 2.0
    
    # Environment (hermetic - no host env leakage)
    env: Dict[str, str] = field(default_factory=dict)
    
    # Volume mounts (read-only where possible)
    mounts: List[MountConfig] = field(default_factory=list)

@dataclass
class MountConfig:
    """Container volume mount configuration."""
    source: str           # Host path
    target: str           # Container path
    read_only: bool = True
```

### ClientCapabilities

```python
@dataclass
class ClientCapabilities:
    """Capabilities to advertise to LSP server."""
    
    text_document: TextDocumentClientCapabilities
    workspace: WorkspaceClientCapabilities
    
    # Batho-specific extensions
    batho_deterministic_mode: bool = True
    batho_include_raw_responses: bool = False  # For debugging
    
@dataclass
class TextDocumentClientCapabilities:
    synchronization: SynchronizationCapabilities
    completion: CompletionCapabilities
    hover: HoverCapabilities
    definition: DefinitionCapabilities
    references: ReferenceCapabilities
    document_symbol: DocumentSymbolCapabilities
    # ... (other capabilities)
    
@dataclass
class DefinitionCapabilities:
    dynamic_registration: bool = False
    link_support: bool = True
```

---

## Adapter Interface

```python
class LSPAdapter(ABC):
    """
    Language-specific adapter for LSP customization.
    
    Each language implements this interface to handle:
    - Project configuration parsing
    - LSP initialization options
    - Response adaptation
    - Path mapping
    """
    
    @abstractmethod
    def get_initialize_options(self, project_root: str) -> Dict[str, Any]:
        """
        Get language-specific initialization options.
        
        Args:
            project_root: Absolute path to project root
            
        Returns:
            Dict of options for LSP initialize request
        """
        pass
    
    @abstractmethod
    def parse_project_config(self, project_root: str) -> ProjectConfig:
        """
        Parse project-specific configuration files.
        
        Args:
            project_root: Absolute path to project root
            
        Returns:
            ProjectConfig with dependencies, paths, etc.
        """
        pass
    
    @abstractmethod
    def adapt_uri(self, uri: str) -> str:
        """
        Adapt URI between LSP and Batho conventions.
        
        Handles path mapping for containerized LSPs.
        """
        pass
    
    @abstractmethod
    def adapt_response(
        self, 
        method: str, 
        raw_response: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Adapt LSP response for Batho consumption.
        
        Args:
            method: LSP method name
            raw_response: Raw JSON-RPC response
            
        Returns:
            Adapted response with language-specific enhancements
        """
        pass
    
    @abstractmethod
    def get_file_patterns(self) -> List[str]:
        """
        Get file glob patterns for this language.
        
        Returns:
            List of patterns, e.g., ["*.py", "**/*.pyi"]
        """
        pass
```

---

## Cache Interface

```python
class LSPCache(ABC):
    """
    Content-addressed cache for LSP responses.
    
    Ensures identical inputs produce cached outputs,
    supporting deterministic behavior.
    """
    
    @abstractmethod
    async def get(
        self, 
        request_hash: str
    ) -> Optional[LSPResponse]:
        """
        Retrieve cached response by request hash.
        
        Args:
            request_hash: SHA256 of request content
            
        Returns:
            Cached response or None
        """
        pass
    
    @abstractmethod
    async def set(
        self,
        request_hash: str,
        response: LSPResponse,
        ttl_seconds: Optional[int] = None
    ) -> None:
        """
        Cache LSP response.
        
        Args:
            request_hash: SHA256 of request content
            response: LSP response to cache
            ttl_seconds: Optional time-to-live
        """
        pass
    
    @abstractmethod
    def compute_request_hash(
        self,
        method: str,
        params: Dict[str, Any],
        lsp_version: str
    ) -> str:
        """
        Compute deterministic hash for request.
        
        Includes method, params, and LSP version for
        content-addressed caching.
        """
        pass
```

---

## Usage Examples

### Basic Usage

```python
async def resolve_python_symbols(file_path: str):
    """Example: Resolve Python symbol definitions."""
    
    config = ContainerConfig(
        image="batho-lsp/python:1.1.350",
        image_digest="sha256:abc123...",
        lsp_command=["pyright-langserver", "--stdio"],
        lsp_version="1.1.350",
        lsp_binary_sha256="sha256:def456..."
    )
    
    async with LSPClient(
        language="python",
        container_config=config,
        adapter=PythonAdapter(),
        timeout_ms=30000
    ) as client:
        
        # Initialize
        await client.initialize(
            root_uri=f"file://{os.getcwd()}",
            capabilities=ClientCapabilities.default()
        )
        
        # Resolve definition
        doc = TextDocumentIdentifier(uri=f"file://{file_path}")
        position = Position(line=10, character=15)
        
        response = await client.textDocument_definition(doc, position)
        
        print(f"Found {len(response.locations)} definitions")
        print(f"Response hash: {response.hash}")
        
        for loc in response.locations:
            print(f"  - {loc.uri}:{loc.range.start.line}")
```

### Batch Resolution

```python
async def resolve_imports_batch(
    client: LSPClient,
    imports: List[Tuple[str, Position]]
) -> BatchResponse:
    """Example: Batch resolve multiple imports."""
    
    requests = [
        ResolutionRequest(
            text_document=TextDocumentIdentifier(uri=uri),
            position=pos,
            method="definition",
            request_id=f"import_{i}"
        )
        for i, (uri, pos) in enumerate(imports)
    ]
    
    response = await client.batch_resolve(
        requests,
        max_parallel=10,
        timeout_ms=60000
    )
    
    if response.failed > 0:
        logger.warning(f"Failed to resolve {response.failed} symbols")
    
    return response
```

### With Caching

```python
async def cached_resolution(
    cache: LSPCache,
    client: LSPClient,
    doc: TextDocumentIdentifier,
    position: Position
) -> DefinitionResponse:
    """Example: Cached symbol resolution."""
    
    # Compute request hash
    request_hash = cache.compute_request_hash(
        method="textDocument/definition",
        params={"uri": doc.uri, "position": position.to_dict()},
        lsp_version=client.lsp_version
    )
    
    # Check cache
    cached = await cache.get(request_hash)
    if cached:
        logger.debug(f"Cache hit for {request_hash[:16]}")
        return cached
    
    # Cache miss - call LSP
    response = await client.textDocument_definition(doc, position)
    
    # Store in cache
    await cache.set(request_hash, response, ttl_seconds=3600)
    
    return response
```

---

## Performance Considerations

### Connection Pooling

```python
class LSPConnectionPool:
    """
    Manages pool of LSP connections for high-throughput scenarios.
    
    Features:
    - Connection reuse across requests
    - Automatic scaling based on load
    - Health checks and automatic replacement
    """
    
    def __init__(
        self,
        max_connections: int = 5,
        min_connections: int = 1,
        idle_timeout_ms: int = 300000
    ):
        ...
```

### Request Batching Strategy

1. **Symbol-level batching**: Group symbols from same file
2. **File-level batching**: Process multiple files in parallel
3. **Cross-file resolution**: Resolve imports before processing dependent files

### Timeout Strategy

```python
TIMEOUT_STRATEGY = {
    "textDocument/definition": 5000,    # 5s for definitions
    "textDocument/references": 10000,   # 10s for references
    "textDocument/hover": 2000,         # 2s for hover
    "textDocument/documentSymbol": 5000, # 5s for symbols
    "workspace/symbol": 15000,          # 15s for workspace search
}
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-03-31 | Initial API specification |

---

**Status**: DRAFT  
**Reviewers**: Batho Core Team  
**Next Review**: 2026-04-07

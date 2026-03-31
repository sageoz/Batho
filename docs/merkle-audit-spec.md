# Merkle Tree Audit Specification

## Overview

The Merkle Tree Audit Layer provides cryptographic proof of context determinism, enabling mathematical verification that agent decisions were made based on identical contexts across time and environments.

## Key Capabilities

1. **Context Merkle Trees**: Cryptographic hash tree of all context inputs
2. **Zero-Drift Validation**: Prove context identity across time
3. **Audit Reports**: Generate signed, timestamped verification documents
4. **Time-Travel Reconstruction**: Rebuild historical contexts exactly

---

## Merkle Tree Structure

### Tree Hierarchy

```
Root Hash (SHA256)
    │
    ├── Source Code Node
    │   ├── file1.py (SHA256 of content)
    │   ├── file2.py (SHA256 of content)
    │   └── file3.py (SHA256 of content)
    │
    ├── LSP Binaries Node
    │   ├── pyright (SHA256 of binary)
    │   ├── gopls (SHA256 of binary)
    │   └── tsserver (SHA256 of binary)
    │
    ├── Configuration Node
    │   ├── tsconfig.json (SHA256 of content)
    │   ├── pyproject.toml (SHA256 of content)
    │   └── batho.yaml (SHA256 of content)
    │
    └── LSP Responses Node
        ├── response1.json (SHA256)
        ├── response2.json (SHA256)
        └── response3.json (SHA256)
```

### Node Types

```python
class MerkleNodeType(IntEnum):
    ROOT = 1
    SOURCE_CODE = 2
    LSP_BINARY = 3
    CONFIG = 4
    LSP_RESPONSE = 5
    METADATA = 6
```

### Hash Algorithm

```python
import hashlib
from typing import List, Optional
from dataclasses import dataclass

@dataclass
class MerkleNode:
    """
    Single node in Merkle tree.
    """
    hash: str                      # SHA256 hex string
    node_type: MerkleNodeType
    name: str                      # Human-readable identifier
    children: List['MerkleNode']   # Child nodes (empty for leaves)
    metadata: Optional[dict]     # Additional node metadata
    
    def compute_hash(self) -> str:
        """
        Compute hash from children (for internal nodes)
        or content (for leaves).
        """
        if self.children:
            # Internal node: hash of concatenated child hashes
            concat = ''.join(c.hash for c in self.children)
            return hashlib.sha256(concat.encode()).hexdigest()
        else:
            # Leaf node: hash is already set from content
            return self.hash
            
    def verify(self) -> bool:
        """Verify node hash matches children."""
        if not self.children:
            return True  # Leaf nodes have no children to verify
            
        computed = self.compute_hash()
        return computed == self.hash
```

---

## Merkle Tree Builder

```python
# batho_core/audit/merkle.py

class MerkleTreeBuilder:
    """
    Builds Merkle trees for context verification.
    """
    
    def __init__(self):
        self.source_files: List[Path] = []
        self.lsp_binaries: Dict[str, str] = {}  # lang -> hash
        self.configs: Dict[str, str] = {}       # path -> hash
        self.lsp_responses: List[tuple] = []    # (request_hash, response_hash)
        
    def add_source_file(self, file_path: Path, content_hash: str) -> 'MerkleTreeBuilder':
        """Add source file to tree."""
        self.source_files.append((file_path, content_hash))
        return self
        
    def add_lsp_binary(self, language: str, binary_hash: str) -> 'MerkleTreeBuilder':
        """Add LSP binary hash."""
        self.lsp_binaries[language] = binary_hash
        return self
        
    def add_config(self, config_path: str, content_hash: str) -> 'MerkleTreeBuilder':
        """Add configuration file hash."""
        self.configs[config_path] = content_hash
        return self
        
    def add_lsp_response(self, request_hash: str, response_hash: str) -> 'MerkleTreeBuilder':
        """Add LSP response hash."""
        self.lsp_responses.append((request_hash, response_hash))
        return self
        
    def build(self) -> MerkleNode:
        """
        Build complete Merkle tree.
        
        Returns:
            Root MerkleNode with full tree structure
        """
        # Build leaf nodes
        source_leaves = [
            MerkleNode(
                hash=content_hash,
                node_type=MerkleNodeType.SOURCE_CODE,
                name=str(file_path),
                children=[],
                metadata={'path': str(file_path)}
            )
            for file_path, content_hash in self.source_files
        ]
        
        lsp_leaves = [
            MerkleNode(
                hash=binary_hash,
                node_type=MerkleNodeType.LSP_BINARY,
                name=f"lsp-{language}",
                children=[],
                metadata={'language': language}
            )
            for language, binary_hash in self.lsp_binaries.items()
        ]
        
        config_leaves = [
            MerkleNode(
                hash=content_hash,
                node_type=MerkleNodeType.CONFIG,
                name=config_path,
                children=[],
                metadata={'path': config_path}
            )
            for config_path, content_hash in self.configs.items()
        ]
        
        response_leaves = [
            MerkleNode(
                hash=response_hash,
                node_type=MerkleNodeType.LSP_RESPONSE,
                name=f"response-{i}",
                children=[],
                metadata={'request_hash': request_hash}
            )
            for i, (request_hash, response_hash) in enumerate(self.lsp_responses)
        ]
        
        # Build internal nodes
        source_node = MerkleNode(
            hash="",  # Computed below
            node_type=MerkleNodeType.SOURCE_CODE,
            name="source-code",
            children=sorted(source_leaves, key=lambda n: n.name),
            metadata={'file_count': len(source_leaves)}
        )
        source_node.hash = source_node.compute_hash()
        
        lsp_node = MerkleNode(
            hash="",
            node_type=MerkleNodeType.LSP_BINARY,
            name="lsp-binaries",
            children=sorted(lsp_leaves, key=lambda n: n.name),
            metadata={'language_count': len(lsp_leaves)}
        )
        lsp_node.hash = lsp_node.compute_hash()
        
        config_node = MerkleNode(
            hash="",
            node_type=MerkleNodeType.CONFIG,
            name="configuration",
            children=sorted(config_leaves, key=lambda n: n.name),
            metadata={'config_count': len(config_leaves)}
        )
        config_node.hash = config_node.compute_hash()
        
        response_node = MerkleNode(
            hash="",
            node_type=MerkleNodeType.LSP_RESPONSE,
            name="lsp-responses",
            children=response_leaves,
            metadata={'response_count': len(response_leaves)}
        )
        response_node.hash = response_node.compute_hash()
        
        # Build root
        root = MerkleNode(
            hash="",
            node_type=MerkleNodeType.ROOT,
            name="context-root",
            children=[source_node, lsp_node, config_node, response_node],
            metadata={
                'timestamp': datetime.utcnow().isoformat(),
                'batho_version': batho.__version__
            }
        )
        root.hash = root.compute_hash()
        
        return root
```

---

## Storage Format

### JSON Serialization

```python
class MerkleStorage:
    """
    Stores and retrieves Merkle trees.
    """
    
    @staticmethod
    def to_json(node: MerkleNode) -> dict:
        """Serialize Merkle tree to JSON."""
        return {
            'hash': node.hash,
            'type': node.node_type.name,
            'name': node.name,
            'metadata': node.metadata,
            'children': [MerkleStorage.to_json(c) for c in node.children]
        }
        
    @staticmethod
    def from_json(data: dict) -> MerkleNode:
        """Deserialize Merkle tree from JSON."""
        return MerkleNode(
            hash=data['hash'],
            node_type=MerkleNodeType[data['type']],
            name=data['name'],
            metadata=data.get('metadata'),
            children=[MerkleStorage.from_json(c) for c in data.get('children', [])]
        )
        
    @staticmethod
    def save(node: MerkleNode, path: Path) -> None:
        """Save Merkle tree to file."""
        data = MerkleStorage.to_json(node)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
            
    @staticmethod
    def load(path: Path) -> MerkleNode:
        """Load Merkle tree from file."""
        with open(path) as f:
            data = json.load(f)
        return MerkleStorage.from_json(data)
```

### Storage Location

```
.sageoz/
├── audit/
│   ├── merkle/
│   │   ├── {commit_sha}.json          # Full Merkle tree
│   │   ├── {commit_sha}.root           # Just root hash
│   │   └── index.json                  # Index of all trees
│   └── reports/
│       └── {timestamp}_{commit_sha}.pdf
└── graphs/
    └── {cache_key}.sageoz_graph
```

---

## Zero-Drift Validation

### Time-Travel Reconstruction

```python
# batho_core/audit/time_travel.py

class ContextReconstructor:
    """
    Reconstructs historical context from stored Merkle tree.
    """
    
    def __init__(
        self,
        git_repo: Path,
        merkle_storage: Path,
        lsp_registry: LSPRegistry
    ):
        self.git_repo = git_repo
        self.merkle_storage = merkle_storage
        self.lsp_registry = lsp_registry
        
    async def reconstruct(
        self,
        merkle_root: str,
        project_path: str
    ) -> ReconstructionResult:
        """
        Reconstruct exact context from historical Merkle tree.
        
        Args:
            merkle_root: Root hash of historical context
            project_path: Path to project
            
        Returns:
            ReconstructionResult with graph and verification status
        """
        # Load historical Merkle tree
        tree = self._load_tree(merkle_root)
        
        # Extract commit SHA from metadata
        commit_sha = tree.metadata.get('commit_sha')
        if not commit_sha:
            raise ReconstructionError("No commit SHA in Merkle tree")
            
        # Checkout exact commit
        await self._checkout_commit(commit_sha)
        
        # Verify source files match
        source_node = self._find_node(tree, MerkleNodeType.SOURCE_CODE)
        source_verified = await self._verify_source_files(source_node)
        
        # Retrieve exact LSP versions
        lsp_node = self._find_node(tree, MerkleNodeType.LSP_BINARY)
        lsp_configs = self._extract_lsp_versions(lsp_node)
        
        # Pull exact LSP containers
        for lang, version_hash in lsp_configs.items():
            await self.lsp_registry.pull_exact_version(lang, version_hash)
            
        # Verify configuration matches
        config_node = self._find_node(tree, MerkleNodeType.CONFIG)
        config_verified = await self._verify_configs(config_node)
        
        # Rebuild graph with exact same inputs
        graph = await self._rebuild_graph(project_path, lsp_configs)
        
        # Compute new Merkle tree
        new_tree = self._build_merkle_tree(graph)
        
        # Compare root hashes
        if new_tree.hash == merkle_root:
            verification_status = "VERIFIED"
            drift_detected = False
        else:
            verification_status = "DRIFT_DETECTED"
            drift_detected = True
            drift_analysis = self._analyze_drift(tree, new_tree)
            
        return ReconstructionResult(
            original_root=merkle_root,
            reconstructed_root=new_tree.hash,
            verification_status=verification_status,
            drift_detected=drift_detected,
            drift_analysis=drift_analysis if drift_detected else None,
            graph=graph if not drift_detected else None
        )
        
    async def _verify_source_files(self, source_node: MerkleNode) -> bool:
        """Verify current source files match historical hashes."""
        for leaf in source_node.children:
            file_path = Path(leaf.metadata['path'])
            actual_hash = self._compute_file_hash(file_path)
            
            if actual_hash != leaf.hash:
                logger.error(
                    f"Source drift: {file_path}\n"
                    f"  Expected: {leaf.hash[:16]}...\n"
                    f"  Actual:   {actual_hash[:16]}..."
                )
                return False
                
        return True
        
    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of file content."""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
```

### Drift Detection

```python
@dataclass
class DriftAnalysis:
    """Analysis of context drift between two Merkle trees."""
    
    drift_type: DriftType
    node_path: str
    expected_hash: str
    actual_hash: str
    description: str
    
enum DriftType:
    SOURCE_CHANGE = 1       # Source file content changed
    LSP_VERSION_CHANGE = 2  # LSP binary version different
    CONFIG_CHANGE = 3       # Configuration file changed
    RESPONSE_CHANGE = 4     # LSP response different (timing/non-determinism)
    MISSING_NODE = 5        # Node missing in reconstruction
    EXTRA_NODE = 6          # Extra node in reconstruction

class DriftAnalyzer:
    """
    Analyzes differences between two Merkle trees.
    """
    
    def analyze(self, expected: MerkleNode, actual: MerkleNode) -> List[DriftAnalysis]:
        """
        Compare two Merkle trees and identify drift.
        
        Args:
            expected: Original Merkle tree
            actual: Reconstructed Merkle tree
            
        Returns:
            List of drift analyses
        """
        drifts = []
        
        # Compare trees recursively
        self._compare_nodes(expected, actual, [], drifts)
        
        return drifts
        
    def _compare_nodes(
        self,
        expected: MerkleNode,
        actual: MerkleNode,
        path: List[str],
        drifts: List[DriftAnalysis]
    ) -> None:
        """Recursively compare nodes."""
        current_path = path + [expected.name]
        
        # Check hash match
        if expected.hash != actual.hash:
            drift_type = self._classify_drift(expected, actual)
            
            drifts.append(DriftAnalysis(
                drift_type=drift_type,
                node_path='/'.join(current_path),
                expected_hash=expected.hash,
                actual_hash=actual.hash,
                description=self._describe_drift(expected, actual, drift_type)
            ))
            
        # Compare children
        exp_children = {c.name: c for c in expected.children}
        act_children = {c.name: c for c in actual.children}
        
        # Check for missing nodes
        for name, child in exp_children.items():
            if name not in act_children:
                drifts.append(DriftAnalysis(
                    drift_type=DriftType.MISSING_NODE,
                    node_path='/'.join(current_path + [name]),
                    expected_hash=child.hash,
                    actual_hash="",
                    description=f"Node {name} missing in reconstruction"
                ))
                
        # Check for extra nodes
        for name, child in act_children.items():
            if name not in exp_children:
                drifts.append(DriftAnalysis(
                    drift_type=DriftType.EXTRA_NODE,
                    node_path='/'.join(current_path + [name]),
                    expected_hash="",
                    actual_hash=child.hash,
                    description=f"Extra node {name} in reconstruction"
                ))
                
        # Recurse into matching children
        for name in exp_children:
            if name in act_children:
                self._compare_nodes(
                    exp_children[name],
                    act_children[name],
                    current_path,
                    drifts
                )
                
    def _classify_drift(
        self,
        expected: MerkleNode,
        actual: MerkleNode
    ) -> DriftType:
        """Classify type of drift based on node types."""
        type_map = {
            MerkleNodeType.SOURCE_CODE: DriftType.SOURCE_CHANGE,
            MerkleNodeType.LSP_BINARY: DriftType.LSP_VERSION_CHANGE,
            MerkleNodeType.CONFIG: DriftType.CONFIG_CHANGE,
            MerkleNodeType.LSP_RESPONSE: DriftType.RESPONSE_CHANGE,
        }
        return type_map.get(expected.node_type, DriftType.SOURCE_CHANGE)
```

---

## Audit Report Generation

```python
# batho_core/audit/reports.py

class AuditReport:
    """
    Generates signed audit reports for verification.
    """
    
    def __init__(self, merkle_tree: MerkleNode, timestamp: datetime):
        self.tree = merkle_tree
        self.timestamp = timestamp
        self.report_id = self._generate_report_id()
        
    def generate_pdf(self, output_path: Path) -> None:
        """Generate PDF audit report."""
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        
        doc = SimpleDocTemplate(str(output_path), pagesize=letter)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        story.append(Paragraph(
            f"<b>Sageoz Batho Audit Report</b>",
            styles['Title']
        ))
        story.append(Spacer(1, 12))
        
        # Report metadata
        story.append(Paragraph(f"<b>Report ID:</b> {self.report_id}", styles['Normal']))
        story.append(Paragraph(f"<b>Timestamp:</b> {self.timestamp.isoformat()}", styles['Normal']))
        story.append(Paragraph(f"<b>Merkle Root:</b> {self.tree.hash}", styles['Normal']))
        story.append(Spacer(1, 12))
        
        # Summary
        story.append(Paragraph("<b>Verification Summary</b>", styles['Heading2']))
        story.append(Paragraph(
            f"This report certifies that the context graph was generated "
            f"with deterministically verifiable inputs. The Merkle root hash "
            f"<code>{self.tree.hash[:32]}...</code> serves as cryptographic "
            f"proof of the exact context state.",
            styles['Normal']
        ))
        story.append(Spacer(1, 12))
        
        # Source files table
        source_node = self._find_node(self.tree, MerkleNodeType.SOURCE_CODE)
        if source_node:
            story.append(Paragraph("<b>Source Files</b>", styles['Heading3']))
            data = [['File Path', 'SHA256 Hash']]
            for leaf in source_node.children:
                data.append([leaf.name, f"{leaf.hash[:32]}..."])
            
            table = Table(data, colWidths=[300, 200])
            table.setStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ])
            story.append(table)
            story.append(Spacer(1, 12))
        
        # LSP binaries table
        lsp_node = self._find_node(self.tree, MerkleNodeType.LSP_BINARY)
        if lsp_node:
            story.append(Paragraph("<b>LSP Binaries</b>", styles['Heading3']))
            data = [['Language', 'Binary Hash']]
            for leaf in lsp_node.children:
                data.append([leaf.metadata['language'], f"{leaf.hash[:32]}..."])
            
            table = Table(data, colWidths=[150, 350])
            table.setStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ])
            story.append(table)
        
        # Signature
        story.append(Spacer(1, 24))
        story.append(Paragraph(
            f"<i>This report is cryptographically signed. "
            f"Verification hash: {self._compute_signature()[:32]}...</i>",
            styles['Italic']
        ))
        
        doc.build(story)
        
    def _compute_signature(self) -> str:
        """Compute digital signature of report."""
        data = f"{self.report_id}:{self.timestamp.isoformat()}:{self.tree.hash}"
        return hashlib.sha256(data.encode()).hexdigest()
```

---

## CLI Integration

### Audit Commands

```python
# batho.py CLI additions

@click.group()
def audit():
    """Audit and verification commands."""
    pass

@audit.command()
@click.argument('project_path')
@click.option('--commit', help='Git commit to verify')
@click.option('--output', '-o', help='Output report path')
def verify(project_path: str, commit: Optional[str], output: Optional[str]):
    """
    Verify context determinism by reconstructing from Merkle tree.
    
    Example:
        batho audit verify ./my-project --commit abc123
    """
    reconstructor = ContextReconstructor(
        git_repo=Path(project_path),
        merkle_storage=Path('.sageoz/audit/merkle'),
        lsp_registry=get_registry()
    )
    
    # Get Merkle root for commit
    if not commit:
        commit = get_current_commit(project_path)
        
    merkle_root = load_merkle_root(commit)
    
    # Reconstruct and verify
    result = reconstructor.reconstruct(merkle_root, project_path)
    
    # Output results
    if result.drift_detected:
        click.echo(click.style("❌ DRIFT DETECTED", fg='red', bold=True))
        click.echo("\nDrift Analysis:")
        for drift in result.drift_analysis:
            click.echo(f"  - {drift.drift_type.name}: {drift.node_path}")
        sys.exit(1)
    else:
        click.echo(click.style("✓ VERIFIED", fg='green', bold=True))
        click.echo(f"Merkle Root: {result.reconstructed_root}")
        click.echo("Context is mathematically identical to original run.")
        
    # Generate report if requested
    if output:
        report = AuditReport(result.tree, datetime.utcnow())
        report.generate_pdf(Path(output))
        click.echo(f"Report saved to: {output}")

@audit.command()
@click.argument('project_path')
@click.option('--since', help='Verify since date (YYYY-MM-DD)')
@click.option('--until', help='Verify until date (YYYY-MM-DD)')
def timeline(project_path: str, since: Optional[str], until: Optional[str]):
    """
    Verify context integrity across timeline.
    
    Example:
        batho audit timeline ./my-project --since 2024-01-01
    """
    commits = get_commits_in_range(project_path, since, until)
    
    click.echo(f"Verifying {len(commits)} commits...")
    
    failures = []
    for commit in commits:
        merkle_root = load_merkle_root(commit)
        result = verify_commit(project_path, merkle_root)
        
        status = "✓" if not result.drift_detected else "✗"
        click.echo(f"{status} {commit[:8]} - {result.verification_status}")
        
        if result.drift_detected:
            failures.append((commit, result))
            
    if failures:
        click.echo(f"\n{len(failures)} commits failed verification")
        sys.exit(1)
    else:
        click.echo("\nAll commits verified successfully")
```

---

## Enterprise Integration

### Audit API

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Sageoz Audit API")

class VerificationRequest(BaseModel):
    project_id: str
    merkle_root: str
    timestamp: datetime

class VerificationResponse(BaseModel):
    verified: bool
    merkle_root: str
    reconstructed_root: Optional[str]
    drift_detected: bool
    report_url: Optional[str]

@app.post("/verify", response_model=VerificationResponse)
async def verify_context(request: VerificationRequest):
    """
    Verify context determinism for enterprise audit.
    
    Returns verification result with optional drift analysis.
    """
    reconstructor = get_reconstructor(request.project_id)
    
    try:
        result = await reconstructor.reconstruct(
            request.merkle_root,
            get_project_path(request.project_id)
        )
        
        if result.drift_detected:
            return VerificationResponse(
                verified=False,
                merkle_root=request.merkle_root,
                reconstructed_root=result.reconstructed_root,
                drift_detected=True,
                report_url=await generate_drift_report(result)
            )
        else:
            return VerificationResponse(
                verified=True,
                merkle_root=request.merkle_root,
                reconstructed_root=result.reconstructed_root,
                drift_detected=False,
                report_url=None
            )
            
    except ReconstructionError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

---

## Security Considerations

1. **Immutable Storage**: Merkle trees stored in append-only log
2. **Digital Signatures**: Reports cryptographically signed
3. **Tamper Detection**: Any modification invalidates Merkle root
4. **Access Control**: Audit data access restricted to authorized auditors
5. **Retention Policy**: Configurable retention for compliance requirements

---

## Performance Targets

| Operation | Target | Notes |
|-----------|--------|-------|
| Merkle tree build | < 100ms | For 1000 files |
| Storage | < 10KB | Per tree (JSON) |
| Verification | < 5s | Full reconstruction |
| Report generation | < 1s | PDF output |
| Timeline verification | < 1min | 100 commits |

---

**Version**: 1.0  
**Status**: DRAFT  
**Last Updated**: 2026-03-31

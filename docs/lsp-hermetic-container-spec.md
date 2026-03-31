# Hermetic LSP Container Specification

## Overview

This document specifies the hermetic containerization system for LSP binaries, ensuring 100% determinism by eliminating host machine environment contamination.

## Core Principles

1. **Immutable Binaries**: Every LSP binary pinned to exact version with SHA256 checksum
2. **No Host Leakage**: Containers have zero access to host environment
3. **Reproducible Builds**: Same inputs always produce identical containers
4. **Network Isolation**: LSP containers have no external network access (unless explicitly required)
5. **Read-Only Filesystems**: Source code mounted read-only where possible

---

## Container Architecture

### Two-Tier Approach

```
┌─────────────────────────────────────────────────────────────┐
│                     Tier 1: Base Image                        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  • Minimal OS (Alpine Linux / Debian Slim)            │   │
│  │  • Language runtimes (Node.js, Go, JDK, etc.)         │   │
│  │  • Common dependencies (git, curl)                    │   │
│  │  • Batho LSP agent utilities                          │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Tier 2: LSP-Specific Layer                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  • LSP binary (exact version, pinned)                 │   │
│  │  • Language-specific dependencies                     │   │
│  │  • Configuration defaults                             │   │
│  │  • Initialization scripts                             │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Base Image Specification

```dockerfile
# Dockerfile.base
FROM alpine:3.19.1@sha256:c5b1261d6d3e43071626931fc004f70149baf1b3f56e

# Pin all packages to specific versions
RUN apk add --no-cache \
    git=2.43.0-r0 \
    curl=8.5.0-r0 \
    ca-certificates=20240226-r0

# Add Batho LSP agent
COPY batho-lsp-agent /usr/local/bin/
RUN chmod +x /usr/local/bin/batho-lsp-agent

# Create workspace directory
WORKDIR /workspace

# Run as non-root user
RUN adduser -D -s /bin/bash batho
USER batho
```

### LSP Registry Format

```yaml
# batho_core/lsp/containers/registry.yaml
version: "1.0"
registry_url: "registry.batho.io/lsp"

languages:
  python:
    name: "Python"
    lsp_name: "Pyright"
    
    versions:
      "1.1.350":
        container:
          base_image: "batho-lsp/base:node20-alpine"
          lsp_binary:
            source: "npm"
            package: "pyright"
            version: "1.1.350"
            sha256: "a1b2c3d4e5f6..."
          
          # Resource limits
          resources:
            memory_mb: 2048
            cpu_cores: 2
            
          # Command to start LSP
          command: ["pyright-langserver", "--stdio"]
          
          # Environment variables
          env:
            NODE_ENV: "production"
            
          # File patterns this LSP handles
          patterns:
            - "*.py"
            - "*.pyi"
            
          # Configuration schema
          config:
            type: "pyright"
            files:
              - "pyrightconfig.json"
              - "pyproject.toml"
            
          # Dependencies for this LSP
          dependencies:
            - name: "node"
              version: "20.11.0"
              sha256: "sha256:xyz789..."
              
        # Verification tests
        verification:
          - type: "startup"
            timeout_ms: 10000
          - type: "initialize"
            test_file: "test_data/simple.py"
          - type: "definition"
            expected_result: "pass"
            
  typescript:
    name: "TypeScript"
    lsp_name: "TypeScript Language Server"
    
    versions:
      "5.3.3":
        container:
          base_image: "batho-lsp/base:node20-alpine"
          lsp_binary:
            source: "npm"
            package: "typescript-language-server"
            version: "5.3.3"
            sha256: "b2c3d4e5f6a7..."
            
          command: ["typescript-language-server", "--stdio"]
          
          patterns:
            - "*.ts"
            - "*.tsx"
            - "*.js"
            - "*.jsx"
            
          config:
            type: "typescript"
            files:
              - "tsconfig.json"
              - "jsconfig.json"
              - "package.json"
              
  go:
    name: "Go"
    lsp_name: "gopls"
    
    versions:
      "0.14.2":
        container:
          base_image: "batho-lsp/base:go1.21-alpine"
          lsp_binary:
            source: "go-install"
            package: "golang.org/x/tools/gopls"
            version: "v0.14.2"
            sha256: "c3d4e5f6a7b8..."
            
          command: ["gopls"]
          
          patterns:
            - "*.go"
            - "go.mod"
            
          config:
            type: "go"
            files:
              - "go.mod"
              - "go.sum"
              
          dependencies:
            - name: "go"
              version: "1.21.6"
              sha256: "sha256:def456..."
              
  # Additional languages follow same pattern...
```

---

## Container Build System

### Build Pipeline

```python
# batho_core/lsp/containers/build/build_lsp_container.py

class ContainerBuilder:
    """
    Builds hermetic LSP containers from registry specification.
    """
    
    def __init__(self, registry_path: str, output_dir: str):
        self.registry = self._load_registry(registry_path)
        self.output_dir = output_dir
        
    async def build(
        self,
        language: str,
        version: str,
        builder: Literal["docker", "podman", "nix"] = "docker"
    ) -> BuildResult:
        """
        Build container for specified language/version.
        
        Args:
            language: Language identifier
            version: LSP version to build
            builder: Container builder tool
            
        Returns:
            BuildResult with image digest and verification status
        """
        spec = self.registry.get_language_spec(language, version)
        
        # Generate Dockerfile or Nix expression
        if builder == "nix":
            build_file = self._generate_nix_flake(spec)
        else:
            build_file = self._generate_dockerfile(spec)
            
        # Build container
        image_tag = f"batho-lsp/{language}:{version}"
        
        if builder == "docker":
            result = await self._build_docker(build_file, image_tag)
        elif builder == "podman":
            result = await self._build_podman(build_file, image_tag)
        else:
            result = await self._build_nix(build_file, image_tag)
            
        # Verify build
        verified = await self._verify_container(result.image_digest, spec)
        
        return BuildResult(
            image_tag=image_tag,
            image_digest=result.image_digest,
            build_time_ms=result.duration_ms,
            verified=verified,
            lsp_binary_sha256=result.lsp_binary_hash
        )
        
    def _generate_dockerfile(self, spec: LanguageSpec) -> str:
        """Generate Dockerfile from specification."""
        
        dockerfile = f"""
FROM {spec.base_image}

# Pin Node.js version (for npm-based LSPs)
{self._generate_runtime_install(spec)}

# Install LSP binary with exact version
{self._generate_lsp_install(spec)}

# Verify binary hash
RUN echo "{spec.lsp_binary.sha256}  $(which {spec.lsp_binary.name})" | sha256sum -c -

# Set up workspace
WORKDIR /workspace
VOLUME /workspace

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \\
    CMD batho-lsp-agent healthcheck || exit 1

# Run as non-root
USER batho

# Default command
CMD {spec.command}
"""
        return dockerfile
        
    def _generate_nix_flake(self, spec: LanguageSpec) -> str:
        """Generate Nix flake for reproducible build."""
        
        flake = f"""
{{
  description = "Hermetic LSP container for {spec.language.name}";
  
  inputs = {{
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-23.11";
    flake-utils.url = "github:numtide/flake-utils";
  }};
  
  outputs = {{ self, nixpkgs, flake-utils }}:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {{
          inherit system;
          config = {{ allowUnfree = true; }};
        }};
        
        lsp-binary = pkgs.{spec.lsp_binary.nix_package}.override {{
          version = "{spec.lsp_binary.version}";
        }};
        
      in {{
        packages.default = pkgs.dockerTools.buildLayeredImage {{
          name = "batho-lsp/{spec.language.id}";
          tag = "{spec.lsp_binary.version}";
          
          contents = [
            lsp-binary
            pkgs.batho-lsp-agent
          ];
          
          config = {{
            Cmd = {spec.command};
            WorkingDir = "/workspace";
            User = "batho";
          }};
        }};
      }});
}}
"""
        return flake
```

### Container Verification

```python
# batho_core/lsp/containers/verify/verify_container_integrity.py

class ContainerVerifier:
    """
    Verifies container integrity before use.
    """
    
    async def verify(
        self,
        image_digest: str,
        spec: LanguageSpec
    ) -> VerificationResult:
        """
        Verify container contains expected LSP binary.
        
        Checks:
        1. Image digest matches registry
        2. LSP binary exists and is executable
        3. LSP binary SHA256 matches
        4. LSP starts successfully
        5. LSP responds to initialize
        """
        
        # Pull and inspect image
        image_info = await self._inspect_image(image_digest)
        
        # Verify digest
        if image_info.digest != image_digest:
            raise VerificationError(f"Digest mismatch: {image_info.digest} != {image_digest}")
            
        # Run container and verify binary
        container = await self._run_ephemeral(image_digest)
        
        try:
            # Check binary exists
            binary_path = await container.exec(["which", spec.lsp_binary.name])
            if not binary_path:
                raise VerificationError(f"LSP binary {spec.lsp_binary.name} not found")
                
            # Verify binary hash
            hash_output = await container.exec([
                "sha256sum", 
                binary_path.strip()
            ])
            actual_hash = hash_output.split()[0]
            
            if actual_hash != spec.lsp_binary.sha256:
                raise VerificationError(
                    f"Binary hash mismatch: {actual_hash[:16]}... != {spec.lsp_binary.sha256[:16]}..."
                )
                
            # Test LSP startup
            startup_ok = await self._test_startup(container, spec)
            if not startup_ok:
                raise VerificationError("LSP failed to start")
                
            # Test initialize
            init_ok = await self._test_initialize(container, spec)
            if not init_ok:
                raise VerificationError("LSP initialize failed")
                
            return VerificationResult(
                passed=True,
                image_digest=image_digest,
                lsp_binary_hash=actual_hash,
                checks_passed=["digest", "binary_exists", "binary_hash", "startup", "initialize"]
            )
            
        finally:
            await container.remove()
            
    async def _test_startup(self, container: Container, spec: LanguageSpec) -> bool:
        """Test LSP process starts without errors."""
        process = await container.run_detached(spec.command)
        
        # Wait for process to be ready
        await asyncio.sleep(2)
        
        # Check process still running
        if not await process.is_running():
            logs = await process.logs()
            logger.error(f"LSP exited early: {logs}")
            return False
            
        await process.stop()
        return True
        
    async def _test_initialize(self, container: Container, spec: LanguageSpec) -> bool:
        """Test LSP responds to initialize request."""
        # Create minimal test
        test_script = f"""
import json
import sys

# Build initialize request
request = {{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {{
        "processId": None,
        "rootUri": "file:///workspace",
        "capabilities": {{}}
    }}
}}

# Send to LSP via stdio
message = json.dumps(request)
header = f"Content-Length: {{len(message)}}\\r\\n\\r\\n"
sys.stdout.write(header + message)
sys.stdout.flush()

# Read response
response = sys.stdin.read()
print(f"Got response: {{response}}", file=sys.stderr)
"""
        result = await container.exec_with_stdio(
            spec.command,
            input_data=test_script
        )
        
        return "initialize" in result and "result" in result
```

---

## Runtime Configuration

### Container Runtime Settings

```python
@dataclass
class ContainerRuntimeConfig:
    """Configuration for running LSP containers."""
    
    # Resource limits
    memory_limit_mb: int = 2048
    cpu_limit: float = 2.0
    
    # Security settings
    read_only_rootfs: bool = True
    no_new_privileges: bool = True
    drop_capabilities: List[str] = field(default_factory=lambda: [
        "ALL"
    ])
    add_capabilities: List[str] = field(default_factory=list)
    
    # Network isolation
    network_mode: Literal["none", "host", "bridge"] = "none"
    
    # Volume mounts
    mounts: List[Mount] = field(default_factory=list)
    
    # Environment (filtered, no host leakage)
    env: Dict[str, str] = field(default_factory=dict)
    
    # Process management
    auto_restart: bool = True
    health_check_interval_ms: int = 30000
    max_restarts: int = 3

@dataclass
class Mount:
    """Volume mount configuration."""
    source: str           # Host path
    target: str           # Container path
    type: Literal["bind", "volume", "tmpfs"] = "bind"
    read_only: bool = True
    propagation: Literal["private", "shared", "slave"] = "private"
```

### Docker/Podman Runtime

```python
class DockerRuntime:
    """Docker runtime for LSP containers."""
    
    async def run(
        self,
        image: str,
        config: ContainerRuntimeConfig,
        command: Optional[List[str]] = None
    ) -> Container:
        """
        Run LSP container with hermetic settings.
        """
        
        # Build docker run command
        args = [
            "docker", "run",
            "--rm",                    # Remove on exit
            "-i",                      # Interactive (for stdio)
            "--network=none",          # No network
            "--read-only",             # Read-only rootfs
            "--security-opt=no-new-privileges:true",
            f"--memory={config.memory_limit_mb}m",
            f"--cpus={config.cpu_limit}",
            "--cap-drop=ALL",
            "--user=batho",            # Non-root user
        ]
        
        # Add mounts
        for mount in config.mounts:
            ro_flag = ",ro" if mount.read_only else ""
            args.extend([
                "-v",
                f"{mount.source}:{mount.target}{ro_flag}"
            ])
            
        # Add environment (explicit only)
        for key, value in config.env.items():
            args.extend(["-e", f"{key}={value}"])
            
        # Add image and command
        args.append(image)
        if command:
            args.extend(command)
            
        # Run container
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        return Container(process=process, config=config)
```

---

## Registry Management

### Adding New LSP Version

```python
# Example: Adding new Pyright version
async def add_pyright_version(version: str):
    """Add new Pyright version to registry."""
    
    # 1. Build container
    builder = ContainerBuilder(
        registry_path="batho_core/lsp/containers/registry.yaml",
        output_dir="/tmp/builds"
    )
    
    result = await builder.build(
        language="python",
        version=version,
        builder="nix"  # Use Nix for reproducibility
    )
    
    # 2. Verify
    if not result.verified:
        raise BuildError(f"Verification failed for Pyright {version}")
        
    # 3. Push to registry
    await push_to_registry(result.image_tag, result.image_digest)
    
    # 4. Update registry.yaml
    registry = load_registry()
    registry.languages["python"].versions[version] = {
        "container": {
            "base_image": "batho-lsp/base:node20-alpine",
            "lsp_binary": {
                "source": "npm",
                "package": "pyright",
                "version": version,
                "sha256": result.lsp_binary_sha256
            },
            "image_digest": result.image_digest
        }
    }
    
    save_registry(registry)
    
    logger.info(f"Added Pyright {version} to registry")
```

### LSP Update Policy

1. **Never auto-update**: LSP versions only change on explicit action
2. **Version pinning**: All versions explicitly pinned in registry
3. **Rollback support**: Previous versions remain available
4. **Security patches**: Only applied after verification testing
5. **Changelog tracking**: All updates documented with rationale

---

## Security Checklist

- [ ] **Rootless containers**: All LSPs run as non-root user
- [ ] **Read-only filesystem**: Source code mounted read-only
- [ ] **No host network**: Containers isolated from host network
- [ ] **Capability dropping**: All capabilities dropped by default
- [ ] **Resource limits**: Memory and CPU constrained
- [ ] **No secrets**: No API keys or credentials in containers
- [ ] **Minimal base**: Only required packages installed
- [ ] **Hash verification**: All binaries verified before use
- [ ] **Audit logging**: All container operations logged
- [ ] **Image signing**: Container images signed with Batho key

---

## Troubleshooting

### Common Issues

1. **Container fails to start**
   - Check resource limits (OOM killed?)
   - Verify image digest matches registry
   - Review LSP binary permissions

2. **LSP responds slowly**
   - Increase memory limit
   - Check for network timeouts (should be none)
   - Verify CPU not throttled

3. **Hash verification fails**
   - Binary may have been tampered with
   - Check registry for correct hash
   - Rebuild container if necessary

4. **Permission denied**
   - Verify read-only mounts correct
   - Check user mapping
   - Review SELinux/AppArmor policies

---

**Version**: 1.0  
**Last Updated**: 2026-03-31

"""
Cloud-native architecture pattern detector.
"""

from typing import Any, Dict, List, Optional, Set
from collections import defaultdict
from pathlib import Path

from .base import PatternDetector, DetectionResult


class CloudNativeDetector(PatternDetector):
    """Detector for cloud-native architecture patterns."""
    
    def __init__(self, min_confidence: float = 0.5):
        super().__init__("cloud_native", min_confidence)
        
        # Kubernetes patterns
        self.k8s_patterns = [
            "deployment", "service", "ingress", "configmap", "secret",
            "kubernetes", "k8s", "apiextensions.k8s.io"
        ]
        
        # Docker patterns
        self.docker_patterns = [
            "docker", "dockerfile", "docker-compose", "container"
        ]
        
        # Serverless patterns
        self.serverless_patterns = {
            "aws": ["lambda", "serverless", "aws-lambda"],
            "azure": ["azure-functions", "functions"],
            "gcp": ["cloud-functions", "google.cloud.functions"]
        }
        
        # Infrastructure as Code patterns
        self.iac_patterns = {
            "terraform": ["terraform", "tf", "hashicorp/terraform"],
            "cloudformation": ["cloudformation", "aws-cfn"],
            "pulumi": ["pulumi", "@pulumi"]
        }
        
        # Cloud provider patterns
        self.cloud_providers = {
            "aws": ["aws", "amazon", "boto3", "aws-sdk"],
            "azure": ["azure", "microsoft.azure", "azure-sdk"],
            "gcp": ["gcp", "google.cloud", "google-cloud"]
        }
    
    def detect(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any],
        rules: Optional[Dict[str, Any]] = None
    ) -> List[DetectionResult]:
        """Detect cloud-native architecture patterns."""
        results = []
        
        # Detect Kubernetes usage
        k8s_result = self._detect_kubernetes(graph, repomap)
        if k8s_result:
            results.append(k8s_result)
        
        # Detect Docker usage
        docker_result = self._detect_docker(graph, repomap)
        if docker_result:
            results.append(docker_result)
        
        # Detect serverless functions
        serverless_result = self._detect_serverless(graph, repomap)
        if serverless_result:
            results.append(serverless_result)
        
        # Detect Infrastructure as Code
        iac_result = self._detect_infrastructure_as_code(graph, repomap)
        if iac_result:
            results.append(iac_result)
        
        # Detect cloud provider usage
        cloud_result = self._detect_cloud_providers(graph, repomap)
        if cloud_result:
            results.append(cloud_result)
        
        # Detect Helm charts
        helm_result = self._detect_helm(graph, repomap)
        if helm_result:
            results.append(helm_result)
        
        return results
    
    def _detect_kubernetes(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect Kubernetes usage."""
        # Find Kubernetes files
        k8s_files = self._find_kubernetes_files(repomap)
        
        # Find Kubernetes imports
        k8s_imports = self._find_imports_by_pattern(graph, self.k8s_patterns)
        
        if not k8s_files and not k8s_imports:
            return None
        
        # Analyze Kubernetes resources
        k8s_resources = self._analyze_kubernetes_resources(k8s_files)
        
        # Calculate confidence
        confidence_indicators = [
            len(k8s_files) > 0,
            len(k8s_imports) > 0,
            len(k8s_resources) > 0,
            any("deployment" in f.lower() for f in k8s_files)
        ]
        
        confidence = self._calculate_confidence(confidence_indicators)
        
        if confidence < self.min_confidence:
            return None
        
        # Create Kubernetes entities
        entities = []
        for resource_type, resources in k8s_resources.items():
            for resource in resources:
                entities.append({
                    "id": f"k8s-{resource_type}-{resource.get('name', 'unknown')}",
                    "name": resource.get("name", f"{resource_type}"),
                    "type": resource_type.capitalize(),
                    "file": resource.get("file"),
                    "description": f"Kubernetes {resource_type}"
                })
        
        return DetectionResult(
            pattern_type="Kubernetes",
            confidence=confidence,
            entities=entities,
            relationships=[],
            metadata={
                "k8s_files": k8s_files,
                "k8s_imports": len(k8s_imports),
                "resource_types": list(k8s_resources.keys()),
                "total_resources": sum(len(r) for r in k8s_resources.values())
            }
        )
    
    def _detect_docker(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect Docker usage."""
        # Find Docker files
        docker_files = self._find_files_by_pattern(repomap, self.docker_patterns)
        
        # Find Docker imports
        docker_imports = self._find_imports_by_pattern(graph, self.docker_patterns)
        
        if not docker_files and not docker_imports:
            return None
        
        # Calculate confidence
        confidence_indicators = [
            any("Dockerfile" in f for f in docker_files),
            any("docker-compose" in f for f in docker_files),
            len(docker_imports) > 0
        ]
        
        confidence = self._calculate_confidence(confidence_indicators)
        
        if confidence < self.min_confidence:
            return None
        
        # Find Docker-related entities
        docker_entities = self._find_entities_by_pattern(
            graph, ["*Container*", "*Docker*"]
        )
        
        return DetectionResult(
            pattern_type="Docker",
            confidence=confidence,
            entities=docker_entities,
            relationships=[],
            metadata={
                "docker_files": docker_files,
                "docker_imports": len(docker_imports),
                "has_dockerfile": any("Dockerfile" in f for f in docker_files),
                "has_compose": any("docker-compose" in f for f in docker_files)
            }
        )
    
    def _detect_serverless(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect serverless function usage."""
        detected_functions = {}
        
        # Check each cloud provider's serverless offering
        for provider, patterns in self.serverless_patterns.items():
            imports = self._find_imports_by_pattern(graph, patterns)
            files = self._find_files_by_pattern(repomap, patterns)
            
            if imports or files:
                detected_functions[provider] = {
                    "imports": imports,
                    "files": files,
                    "count": len(imports) + len(files)
                }
        
        if not detected_functions:
            return None
        
        # Calculate confidence
        confidence = min(1.0, len(detected_functions) / 2.0)
        
        if confidence < self.min_confidence:
            return None
        
        # Create serverless entities
        entities = []
        for provider, info in detected_functions.items():
            entities.append({
                "id": f"serverless-{provider}",
                "name": f"{provider.upper()} Serverless",
                "type": "ServerlessFunction",
                "function_count": info["count"],
                "description": f"Serverless functions on {provider.upper()}"
            })
        
        return DetectionResult(
            pattern_type="Serverless",
            confidence=confidence,
            entities=entities,
            relationships=[],
            metadata={
                "providers": list(detected_functions.keys()),
                "total_functions": sum(info["count"] for info in detected_functions.values())
            }
        )
    
    def _detect_infrastructure_as_code(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect Infrastructure as Code usage."""
        detected_iac = {}
        
        # Check each IaC tool
        for tool, patterns in self.iac_patterns.items():
            files = self._find_files_by_pattern(repomap, patterns)
            imports = self._find_imports_by_pattern(graph, patterns)
            
            if files or imports:
                detected_iac[tool] = {
                    "files": files,
                    "imports": imports,
                    "count": len(files) + len(imports)
                }
        
        if not detected_iac:
            return None
        
        # Calculate confidence
        confidence = min(1.0, len(detected_iac) / 2.0)
        
        if confidence < self.min_confidence:
            return None
        
        # Create IaC entities
        entities = []
        for tool, info in detected_iac.items():
            entities.append({
                "id": f"iac-{tool}",
                "name": tool.title(),
                "type": "InfrastructureAsCode",
                "resource_count": info["count"],
                "description": f"Infrastructure as Code with {tool}"
            })
        
        return DetectionResult(
            pattern_type="InfrastructureAsCode",
            confidence=confidence,
            entities=entities,
            relationships=[],
            metadata={
                "tools": list(detected_iac.keys()),
                "total_resources": sum(info["count"] for info in detected_iac.values())
            }
        )
    
    def _detect_cloud_providers(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect cloud provider usage."""
        detected_providers = {}
        
        # Check each cloud provider
        for provider, patterns in self.cloud_providers.items():
            imports = self._find_imports_by_pattern(graph, patterns)
            files = self._find_files_by_pattern(repomap, patterns)
            
            if imports or files:
                detected_providers[provider] = {
                    "imports": imports,
                    "files": files,
                    "services": len(set(imp.get("target", "").split(".")[0] 
                                   for imp in imports[:5]))  # Top 5 unique services
                }
        
        if not detected_providers:
            return None
        
        # Calculate confidence
        confidence = min(1.0, len(detected_providers) / 2.0)
        
        if confidence < self.min_confidence:
            return None
        
        # Create cloud provider entities
        entities = []
        for provider, info in detected_providers.items():
            entities.append({
                "id": f"cloud-{provider}",
                "name": provider.upper(),
                "type": "CloudProvider",
                "service_count": info["services"],
                "description": f"Cloud services on {provider.upper()}"
            })
        
        return DetectionResult(
            pattern_type="CloudProvider",
            confidence=confidence,
            entities=entities,
            relationships=[],
            metadata={
                "providers": list(detected_providers.keys()),
                "multi_cloud": len(detected_providers) > 1
            }
        )
    
    def _detect_helm(
        self,
        graph: Dict[str, Any],
        repomap: Dict[str, Any]
    ) -> Optional[DetectionResult]:
        """Detect Helm chart usage."""
        helm_patterns = ["helm", "Chart.yaml", "values.yaml", "templates/"]
        
        # Find Helm files
        helm_files = self._find_files_by_pattern(repomap, helm_patterns)
        
        if not helm_files:
            return None
        
        # Check for Chart.yaml
        has_chart = any("Chart.yaml" in f for f in helm_files)
        has_templates = any("templates/" in f for f in helm_files)
        
        # Calculate confidence
        confidence_indicators = [
            has_chart,
            has_templates,
            len(helm_files) > 2
        ]
        
        confidence = self._calculate_confidence(confidence_indicators)
        
        if confidence < self.min_confidence:
            return None
        
        # Find Helm-related entities
        helm_entities = self._find_entities_by_pattern(
            graph, ["*Helm*", "*Chart*", "*Template*"]
        )
        
        return DetectionResult(
            pattern_type="Helm",
            confidence=confidence,
            entities=helm_entities,
            relationships=[],
            metadata={
                "helm_files": helm_files,
                "has_chart": has_chart,
                "has_templates": has_templates
            }
        )
    
    def _find_kubernetes_files(self, repomap: Dict[str, Any]) -> List[str]:
        """Find Kubernetes manifest files."""
        k8s_files = []
        k8s_extensions = [".yaml", ".yml"]
        
        for file_path in repomap.get("files", {}).keys():
            file_lower = file_path.lower()
            
            # Check for Kubernetes patterns in path
            if (any(pattern in file_lower for pattern in self.k8s_patterns) or
                any(pattern in file_lower for pattern in ["k8s/", "deploy/", "manifest/"])):
                
                # Check file extension
                if any(file_path.endswith(ext) for ext in k8s_extensions):
                    k8s_files.append(file_path)
        
        return k8s_files
    
    def _analyze_kubernetes_resources(
        self,
        k8s_files: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Analyze Kubernetes resources from manifest files."""
        resources = defaultdict(list)
        
        # This is a simplified analysis based on file names
        # In a real implementation, you would parse the YAML files
        for file_path in k8s_files:
            file_name = Path(file_path).name.lower()
            
            if "deployment" in file_name:
                resources["deployment"].append({
                    "name": Path(file_path).stem,
                    "file": file_path
                })
            elif "service" in file_name:
                resources["service"].append({
                    "name": Path(file_path).stem,
                    "file": file_path
                })
            elif "ingress" in file_name:
                resources["ingress"].append({
                    "name": Path(file_path).stem,
                    "file": file_path
                })
            elif "configmap" in file_name:
                resources["configmap"].append({
                    "name": Path(file_path).stem,
                    "file": file_path
                })
            elif "secret" in file_name:
                resources["secret"].append({
                    "name": Path(file_path).stem,
                    "file": file_path
                })
        
        return dict(resources)

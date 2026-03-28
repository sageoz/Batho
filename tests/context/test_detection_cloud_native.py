"""
Tests for cloud-native architecture pattern detection.
"""

import pytest

from batho_core.context.c4.detection.cloud_native import CloudNativeDetector


class TestCloudNativeDetector:
    """Test cases for CloudNativeDetector."""
    
    def test_initialization(self):
        """Test detector initialization."""
        detector = CloudNativeDetector(min_confidence=0.6)
        assert detector.name == "cloud_native"
        assert detector.min_confidence == 0.6
    
    def test_detect_kubernetes(self):
        """Test Kubernetes detection."""
        detector = CloudNativeDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "kubernetes"},
                {"type": "IMPORTS", "target": "io.k8s"}
            ]
        }
        
        repomap = {
            "files": {
                "k8s/deployment.yaml": {"size": 100},
                "k8s/service.yaml": {"size": 50},
                "k8s/ingress.yaml": {"size": 75}
            }
        }
        
        results = detector.detect(graph, repomap)
        
        # Should detect Kubernetes
        k8s_results = [r for r in results if r.pattern_type == "Kubernetes"]
        assert len(k8s_results) > 0
        assert "deployment" in k8s_results[0].metadata["resource_types"]
        assert "service" in k8s_results[0].metadata["resource_types"]
    
    def test_detect_docker(self):
        """Test Docker detection."""
        detector = CloudNativeDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "docker"}
            ]
        }
        
        repomap = {
            "files": {
                "Dockerfile": {"size": 100},
                "docker-compose.yml": {"size": 200},
                "docker/Dockerfile.dev": {"size": 50}
            }
        }
        
        results = detector.detect(graph, repomap)
        
        # Should detect Docker
        docker_results = [r for r in results if r.pattern_type == "Docker"]
        assert len(docker_results) > 0
        assert docker_results[0].metadata["has_dockerfile"] is True
        assert docker_results[0].metadata["has_compose"] is True
    
    def test_detect_serverless(self):
        """Test serverless function detection."""
        detector = CloudNativeDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "aws-lambda"},
                {"type": "IMPORTS", "target": "azure-functions"}
            ]
        }
        
        repomap = {
            "files": {
                "lambda/handler.py": {"size": 100},
                "functions/api/main.py": {"size": 150}
            }
        }
        
        results = detector.detect(graph, repomap)
        
        # Should detect serverless
        serverless_results = [r for r in results if r.pattern_type == "Serverless"]
        assert len(serverless_results) > 0
        assert "aws" in serverless_results[0].metadata["providers"]
        assert "azure" in serverless_results[0].metadata["providers"]
    
    def test_detect_infrastructure_as_code(self):
        """Test Infrastructure as Code detection."""
        detector = CloudNativeDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "terraform"},
                {"type": "IMPORTS", "target": "pulumi"}
            ]
        }
        
        repomap = {
            "files": {
                "infra/main.tf": {"size": 200},
                "infra/variables.tf": {"size": 50},
                "pulumi/Pulumi.yaml": {"size": 100}
            }
        }
        
        results = detector.detect(graph, repomap)
        
        # Should detect IaC
        iac_results = [r for r in results if r.pattern_type == "InfrastructureAsCode"]
        assert len(iac_results) > 0
        assert "terraform" in iac_results[0].metadata["tools"]
        assert "pulumi" in iac_results[0].metadata["tools"]
    
    def test_detect_cloud_providers(self):
        """Test cloud provider detection."""
        detector = CloudNativeDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "boto3"},
                {"type": "IMPORTS", "target": "aws-sdk"},
                {"type": "IMPORTS", "target": "azure-sdk"}
            ]
        }
        
        results = detector.detect(graph, repomap={})
        
        # Should detect cloud providers
        cloud_results = [r for r in results if r.pattern_type == "CloudProvider"]
        assert len(cloud_results) > 0
        assert "aws" in cloud_results[0].metadata["providers"]
        assert "azure" in cloud_results[0].metadata["providers"]
        assert cloud_results[0].metadata["multi_cloud"] is True
    
    def test_detect_helm(self):
        """Test Helm chart detection."""
        detector = CloudNativeDetector()
        
        repomap = {
            "files": {
                "helm/Chart.yaml": {"size": 100},
                "helm/values.yaml": {"size": 150},
                "helm/templates/deployment.yaml": {"size": 200},
                "helm/templates/service.yaml": {"size": 100}
            }
        }
        
        results = detector.detect(graph={}, repomap=repomap)
        
        # Should detect Helm
        helm_results = [r for r in results if r.pattern_type == "Helm"]
        assert len(helm_results) > 0
        assert helm_results[0].metadata["has_chart"] is True
        assert helm_results[0].metadata["has_templates"] is True
    
    def test_no_cloud_native_patterns(self):
        """Test when no cloud-native patterns are found."""
        detector = CloudNativeDetector()
        
        graph = {
            "relationships": [
                {"type": "IMPORTS", "target": "flask"},
                {"type": "IMPORTS", "target": "sqlalchemy"}
            ]
        }
        
        repomap = {
            "files": {
                "app.py": {"size": 100},
                "models.py": {"size": 50}
            }
        }
        
        results = detector.detect(graph, repomap)
        
        # Should not detect any patterns
        assert len(results) == 0

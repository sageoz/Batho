"""Tests for new language, framework, and infrastructure detection plugins."""

import pytest
from pathlib import Path
from batho.bsg.rules import list_builtin_plugins, load_effective_rules

MIN_EXPECTED_RULES_FROM_NEW_PLUGINS = 50


class TestNewLanguageDetection:
    """Test new language detection plugins."""

    def test_all_new_language_plugins_loaded(self):
        """Verify all 9 new language detection plugins are loaded."""
        plugins = list_builtin_plugins()
        
        expected_languages = [
            'bsg_detection_csharp',
            'bsg_detection_php',
            'bsg_detection_ruby',
            'bsg_detection_swift',
            'bsg_detection_kotlin',
            'bsg_detection_scala',
            'bsg_detection_cpp',
            'bsg_detection_elixir',
            'bsg_detection_dart',
        ]
        
        for plugin_id in expected_languages:
            assert plugin_id in plugins, f"Plugin {plugin_id} not found in builtin plugins"

    def test_csharp_detection_rules(self, tmp_path):
        """Test C# language detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_detection_csharp"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-csharp" in rule_ids
        assert "detect-nuget" in rule_ids
        assert "detect-aspnet" in rule_ids

    def test_php_detection_rules(self, tmp_path):
        """Test PHP language detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_detection_php"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-php" in rule_ids
        assert "detect-laravel" in rule_ids
        assert "detect-symfony" in rule_ids

    def test_ruby_detection_rules(self, tmp_path):
        """Test Ruby language detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_detection_ruby"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-ruby" in rule_ids
        assert "detect-rails" in rule_ids

    def test_swift_detection_rules(self, tmp_path):
        """Test Swift language detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_detection_swift"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-swift" in rule_ids
        assert "detect-swiftui" in rule_ids
        assert "detect-vapor" in rule_ids

    def test_kotlin_detection_rules(self, tmp_path):
        """Test Kotlin language detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_detection_kotlin"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-kotlin" in rule_ids
        assert "detect-ktor" in rule_ids

    def test_scala_detection_rules(self, tmp_path):
        """Test Scala language detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_detection_scala"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-scala" in rule_ids
        assert "detect-sbt" in rule_ids
        assert "detect-play-framework" in rule_ids

    def test_cpp_detection_rules(self, tmp_path):
        """Test C++ language detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_detection_cpp"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-cpp" in rule_ids
        assert "detect-cmake" in rule_ids
        assert "detect-qt" in rule_ids

    def test_elixir_detection_rules(self, tmp_path):
        """Test Elixir language detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_detection_elixir"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-elixir" in rule_ids
        assert "detect-phoenix" in rule_ids

    def test_dart_detection_rules(self, tmp_path):
        """Test Dart language detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_detection_dart"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-dart" in rule_ids
        assert "detect-flutter" in rule_ids


class TestNewFrameworkDetection:
    """Test new framework detection plugins."""

    def test_all_new_framework_plugins_loaded(self):
        """Verify all new framework detection plugins are loaded."""
        plugins = list_builtin_plugins()
        
        expected_frameworks = [
            'bsg_framework_react',
            'bsg_framework_vue',
            'bsg_framework_angular',
            'bsg_framework_django',
            'bsg_framework_flask',
        ]
        
        for plugin_id in expected_frameworks:
            assert plugin_id in plugins, f"Plugin {plugin_id} not found in builtin plugins"

    def test_react_framework_rules(self, tmp_path):
        """Test React framework detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_framework_react"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-react" in rule_ids
        assert "detect-nextjs" in rule_ids
        assert "detect-gatsby" in rule_ids

    def test_vue_framework_rules(self, tmp_path):
        """Test Vue.js framework detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_framework_vue"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-vue" in rule_ids
        assert "detect-nuxtjs" in rule_ids

    def test_django_framework_rules(self, tmp_path):
        """Test Django framework detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_framework_django"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-django" in rule_ids
        assert "detect-django-rest-framework" in rule_ids

    def test_flask_framework_rules(self, tmp_path):
        """Test Flask framework detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_framework_flask"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-flask" in rule_ids
        assert "detect-fastapi" in rule_ids


class TestNewInfrastructureDetection:
    """Test new infrastructure detection plugins."""

    def test_all_new_infrastructure_plugins_loaded(self):
        """Verify all new infrastructure detection plugins are loaded."""
        plugins = list_builtin_plugins()
        
        expected_infra = [
            'bsg_detection_cloud_providers',
            'bsg_detection_cicd',
            'bsg_detection_test_frameworks',
        ]
        
        for plugin_id in expected_infra:
            assert plugin_id in plugins, f"Plugin {plugin_id} not found in builtin plugins"

    def test_cloud_provider_detection_rules(self, tmp_path):
        """Test cloud provider detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_detection_cloud_providers"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-aws" in rule_ids
        assert "detect-gcp" in rule_ids
        assert "detect-azure" in rule_ids
        assert "detect-terraform" in rule_ids

    def test_cicd_detection_rules(self, tmp_path):
        """Test CI/CD platform detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_detection_cicd"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-github-actions" in rule_ids
        assert "detect-gitlab-ci" in rule_ids
        assert "detect-jenkins" in rule_ids

    def test_test_framework_detection_rules(self, tmp_path):
        """Test framework detection rules."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": ["bsg_detection_test_frameworks"],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        rule_ids = [r.rule_id for r in rules]
        assert "detect-pytest" in rule_ids
        assert "detect-jest" in rule_ids
        assert "detect-junit" in rule_ids


class TestPluginIntegration:
    """Test integration of new plugins with existing system."""

    def test_all_new_plugins_load_together(self, tmp_path):
        """Test that all new plugins can be loaded simultaneously."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": [
                "bsg_detection_csharp",
                "bsg_detection_php",
                "bsg_detection_ruby",
                "bsg_detection_swift",
                "bsg_detection_kotlin",
                "bsg_detection_scala",
                "bsg_detection_cpp",
                "bsg_detection_elixir",
                "bsg_detection_dart",
                "bsg_framework_react",
                "bsg_framework_vue",
                "bsg_framework_angular",
                "bsg_framework_django",
                "bsg_framework_flask",
                "bsg_detection_cloud_providers",
                "bsg_detection_cicd",
                "bsg_detection_test_frameworks",
            ],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        # Should have loaded all rules from all plugins
        assert stats["rules_loaded"] > MIN_EXPECTED_RULES_FROM_NEW_PLUGINS
        assert stats.get("errors", []) == []

    def test_new_plugins_with_existing_foundation(self, tmp_path):
        """Test new plugins work alongside existing foundation plugins."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": [
                "bsg_graph_foundation",
                "bsg_detection_foundation",
                "bsg_detection_csharp",
                "bsg_framework_react",
            ],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        assert stats["rules_loaded"] > 0
        assert stats.get("errors", []) == []
        
        # Check mix of old and new rules
        rule_ids = [r.rule_id for r in rules]
        assert "detect-python" in rule_ids  # From existing foundation
        assert "detect-csharp" in rule_ids  # From new plugin
        assert "detect-react" in rule_ids   # From new framework plugin

    def test_priority_ordering_with_new_plugins(self, tmp_path):
        """Test that priority ordering works correctly with new plugins."""
        rules_config = {
            "enabled": True,
            "builtin_plugins": [
                "bsg_detection_foundation",
                "bsg_detection_csharp",
                "bsg_detection_php",
            ],
        }
        
        rules, stats = load_effective_rules(rules_config, tmp_path)
        
        # Rules should be sorted by priority (ascending - lowest priority first)
        priorities = [r.priority for r in rules]
        assert priorities == sorted(priorities)

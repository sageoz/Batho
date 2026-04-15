from __future__ import annotations

from textwrap import dedent

HOOKS_SCHEMA_VERSION = "hooks.v1"
DEFAULT_HOOKS_CONFIG_REL_PATH = ".batho/hooks.yaml"
DEFAULT_ROOT_CONFIG_REL_PATH = "batho.yaml"
MANAGED_HOOK_MARKER = "# BATHO_MANAGED_HOOK"

SUPPORTED_GIT_CLIENT_HOOKS: tuple[str, ...] = (
    "applypatch-msg",
    "pre-applypatch",
    "post-applypatch",
    "pre-commit",
    "prepare-commit-msg",
    "commit-msg",
    "post-commit",
    "pre-rebase",
    "post-checkout",
    "post-merge",
    "pre-push",
    "pre-auto-gc",
    "post-rewrite",
    "sendemail-validate",
    "fsmonitor-watchman",
    "p4-pre-submit",
    "post-index-change",
)

BUILTIN_TEMPLATE_CATALOG: dict[str, dict[str, str]] = {
    "code-quality": {
        "description": "Run lint and formatting checks.",
        "run": "echo '[batho hooks] code-quality: run your lint/format checks'",
    },
    "secret-scan": {
        "description": "Run secret and unsafe pattern scanning.",
        "run": "echo '[batho hooks] secret-scan: run your secret scanner'",
    },
    "validation-tests": {
        "description": "Run targeted validation tests.",
        "run": "echo '[batho hooks] validation-tests: run targeted tests'",
    },
    "compliance-check": {
        "description": "Run optional compliance checks.",
        "run": "echo '[batho hooks] compliance-check: run compliance/SBOM checks'",
    },
    "batho-index": {
        "description": "Refresh Batho index.",
        "run": "batho index --root .",
    },
    "batho-patch-scan": {
        "description": "Preview Batho incremental patch scan.",
        "run": "batho patch --root . --scan --dry-run",
    },
    "batho-stats": {
        "description": "Print Batho repository stats.",
        "run": "batho stats --root .",
    },
}


def starter_hooks_yaml() -> str:
    return dedent("""\
        version: hooks.v1
        defaults:
          shell: sh
          timeout_seconds: 300
          fail_fast: true
          env: {}

        templates:
          custom-team-check:
            description: Team-specific guardrail
            run: echo "[batho hooks] add your team check here"

        hooks:
          pre-commit:
            enabled: true
            description: Enterprise pre-commit gate
            stages:
              - template: code-quality
              - template: secret-scan
              - template: batho-index

          pre-push:
            enabled: true
            description: Enterprise pre-push validation
            stages:
              - template: validation-tests
              - template: batho-patch-scan

          enterprise-nightly:
            enabled: true
            description: Custom non-git hook runnable via batho hooks run
            stages:
              - template: custom-team-check
        """)

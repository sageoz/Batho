"""
stack_detector.py — Project stack and framework detection.

This module provides heuristic detection of core frameworks from project
configuration files like pyproject.toml, package.json, requirements.txt, etc.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from batho.utils.dependencies import (
    parse_cargo_toml_file,
    parse_package_json_file,
    parse_pyproject_toml_file,
    parse_requirements_txt_file,
    parse_setup_py_file,
)
from batho.utils.ignore import is_ignored, load_ignore_spec
from batho.utils.logging import get_logger

logger = get_logger(__name__, component="stack_detector")

# Framework mapping for Python dependencies
PYTHON_FRAMEWORK_MAP: dict[str, str] = {
    # Web frameworks
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "tornado": "Tornado",
    "bottle": "Bottle",
    "pyramid": "Pyramid",
    "starlette": "Starlette",
    "falcon": "Falcon",
    "sanic": "Sanic",
    # Database ORMs
    "sqlalchemy": "SQLAlchemy",
    "peewee": "Peewee",
    "tortoise-orm": "Tortoise ORM",
    "pony": "Pony ORM",
    "django-orm": "Django ORM",
    # Validation/Serialization
    "pydantic": "Pydantic",
    "marshmallow": "Marshmallow",
    "cerberus": "Cerberus",
    # Testing
    "pytest": "Pytest",
    "pytest-asyncio": "Pytest Asyncio",
    "pytest-cov": "Pytest Coverage",
    "unittest": "Unittest",
    "nose": "Nose",
    "tox": "Tox",
    # ASGI/WSGI servers
    "uvicorn": "Uvicorn",
    "gunicorn": "Gunicorn",
    "daphne": "Daphne",
    "hypercorn": "Hypercorn",
    # HTTP clients
    "requests": "Requests",
    "httpx": "HTTPX",
    "aiohttp": "Aiohttp",
    # CLI frameworks
    "click": "Click",
    "typer": "Typer",
    "argparse": "Argparse",
    # Configuration
    "python-dotenv": "python-dotenv",
    "pydantic-settings": "Pydantic Settings",
    # Documentation
    "sphinx": "Sphinx",
    "mkdocs": "MkDocs",
    # Async utilities
    "asyncio": "Asyncio",
    "anyio": "AnyIO",
    "trio": "Trio",
    # Logging
    "structlog": "Structlog",
    # Tree-sitter
    "tree-sitter": "Tree-sitter",
    # LLM/AI libraries
    "litellm": "LiteLLM",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "langchain": "LangChain",
    "transformers": "Hugging Face Transformers",
    # MCP
    "fastmcp": "FastMCP",
    "mcp": "MCP",
    # Database drivers
    "aiosqlite": "aiosqlite",
    "asyncpg": "AsyncPG",
    "psycopg": "Psycopg",
    "pymongo": "PyMongo",
    "redis": "Redis",
    # Packaging/Build tools
    "hatchling": "Hatchling",
    "setuptools": "Setuptools",
    "poetry": "Poetry",
    "flit": "Flit",
    "pdm": "PDM",
    # Type checking
    "mypy": "MyPy",
    "pyright": "Pyright",
    "pytype": "Pytype",
    # Linting/Formatting
    "ruff": "Ruff",
    "black": "Black",
    "isort": "isort",
    "flake8": "Flake8",
    "pylint": "Pylint",
    "bandit": "Bandit",
    "pre-commit": "Pre-commit",
    # Data/ML
    "pandas": "Pandas",
    "numpy": "NumPy",
    "polars": "Polars",
    "scikit-learn": "Scikit-learn",
    "sklearn": "Scikit-learn",
    "tensorflow": "TensorFlow",
    "torch": "PyTorch",
    "pytorch": "PyTorch",
    "jax": "JAX",
    "xgboost": "XGBoost",
    "lightgbm": "LightGBM",
    "catboost": "CatBoost",
    "mlflow": "MLflow",
    "transformers": "Transformers",
    "sentence-transformers": "Transformers",
    "opencv-python": "OpenCV",
    "spacy": "spaCy",
    "nltk": "NLTK",
    "statsmodels": "Statsmodels",
    "prophet": "Prophet",
    "arima": "ARIMA",
    "pytorch-lightning": "PyTorch Lightning",
    # Utilities
    "pyyaml": "PyYAML",
    "toml": "TOML",
    "jinja2": "Jinja2",
    "jmespath": "JMESPath",
    "rich": "Rich",
    "tqdm": "tqdm",
    "colorama": "Colorama",
    "pillow": "Pillow",
}

# Framework mapping for Node.js dependencies
NODE_FRAMEWORK_MAP: dict[str, str] = {
    # Frontend frameworks
    "react": "React",
    "react-dom": "React DOM",
    "vue": "Vue.js",
    "@vue/core": "Vue.js",
    "angular": "Angular",
    "@angular/core": "Angular",
    "svelte": "Svelte",
    "solid-js": "SolidJS",
    "preact": "Preact",
    "alpinejs": "Alpine.js",
    "lit": "Lit",
    # Backend frameworks
    "express": "Express",
    "fastify": "Fastify",
    "koa": "Koa",
    "nest": "NestJS",
    "@nestjs/core": "NestJS",
    "hapi": "Hapi",
    "sails": "Sails.js",
    "loopback": "LoopBack",
    "feathers": "FeathersJS",
    "adonis": "AdonisJS",
    "@adonisjs/core": "AdonisJS",
    # Full-stack/meta frameworks
    "next": "Next.js",
    "nuxt": "Nuxt.js",
    "remix": "Remix",
    "@remix-run/react": "Remix",
    "astro": "Astro",
    "sveltekit": "SvelteKit",
    "@sveltejs/kit": "SvelteKit",
    "gatsby": "Gatsby",
    "redwood": "RedwoodJS",
    "@redwoodjs/core": "RedwoodJS",
    "blitz": "Blitz.js",
    # Testing
    "jest": "Jest",
    "vitest": "Vitest",
    "mocha": "Mocha",
    "jasmine": "Jasmine",
    "cypress": "Cypress",
    "playwright": "Playwright",
    "@playwright/test": "Playwright",
    "karma": "Karma",
    "ava": "AVA",
    "tap": "TAP",
    "tape": "Tape",
    "uvu": "uvu",
    # Build tools
    "webpack": "Webpack",
    "rollup": "Rollup",
    "parcel": "Parcel",
    "esbuild": "esbuild",
    "vite": "Vite",
    "turbopack": "Turbopack",
    "swc": "SWC",
    "@swc/core": "SWC",
    "bun": "Bun",
    # TypeScript
    "typescript": "TypeScript",
    "ts-node": "ts-node",
    "tsx": "tsx",
    # Linters/Formatters
    "eslint": "ESLint",
    "prettier": "Prettier",
    "biome": "Biome",
    "@biomejs/biome": "Biome",
    "rome": "Rome",
    # State management
    "redux": "Redux",
    "@reduxjs/toolkit": "Redux Toolkit",
    "mobx": "MobX",
    "zustand": "Zustand",
    "recoil": "Recoil",
    "jotai": "Jotai",
    "valtio": "Valtio",
    "pinia": "Pinia",
    "xstate": "XState",
    # Styling
    "tailwindcss": "Tailwind CSS",
    "styled-components": "styled-components",
    "emotion": "Emotion",
    "@emotion/react": "Emotion",
    "sass": "Sass",
    "less": "Less",
    "stylus": "Stylus",
    "postcss": "PostCSS",
    # UI component libraries
    "@mui/material": "Material UI",
    "@material-ui/core": "Material UI",
    "antd": "Ant Design",
    "chakra-ui": "Chakra UI",
    "@chakra-ui/react": "Chakra UI",
    "bootstrap": "Bootstrap",
    "react-bootstrap": "React Bootstrap",
    "semantic-ui-react": "Semantic UI",
    "bulma": "Bulma",
    "vuetify": "Vuetify",
    "element-ui": "Element UI",
    "@element-plus": "Element Plus",
    "primevue": "PrimeVue",
    "primereact": "PrimeReact",
    "shadcn-ui": "shadcn/ui",
    "radix-ui": "Radix UI",
    "@radix-ui": "Radix UI",
    "headlessui": "Headless UI",
    "@headlessui/react": "Headless UI",
    # Database/ORM
    "prisma": "Prisma",
    "@prisma/client": "Prisma",
    "sequelize": "Sequelize",
    "typeorm": "TypeORM",
    "mongoose": "Mongoose",
    "knex": "Knex.js",
    "drizzle-orm": "Drizzle ORM",
    "@drizzle-team/brocli": "Drizzle",
    "firebase": "Firebase",
    "@firebase/app": "Firebase",
    "supabase": "Supabase",
    "@supabase/supabase-js": "Supabase",
    "appwrite": "Appwrite",
    # GraphQL
    "graphql": "GraphQL",
    "apollo-client": "Apollo Client",
    "@apollo/client": "Apollo Client",
    "apollo-server": "Apollo Server",
    "@apollo/server": "Apollo Server",
    "relay": "Relay",
    "urql": "URQL",
    # Real-time
    "socket.io": "Socket.IO",
    "socket.io-client": "Socket.IO Client",
    "ws": "ws",
    "mqtt": "MQTT",
    # Authentication
    "next-auth": "NextAuth.js",
    "@auth/core": "Auth.js",
    "passport": "Passport.js",
    "jsonwebtoken": "JWT",
    "bcrypt": "bcrypt",
    "argon2": "Argon2",
    "auth0": "Auth0",
    "@auth0/auth0-react": "Auth0",
    "clerk": "Clerk",
    "@clerk/nextjs": "Clerk",
    "firebase-auth": "Firebase Auth",
    "@firebase/auth": "Firebase Auth",
    # API clients
    "axios": "Axios",
    "fetch": "Fetch API",
    "node-fetch": "node-fetch",
    "got": "Got",
    "ky": "Ky",
    "superagent": "SuperAgent",
    "@tanstack/react-query": "React Query",
    "react-query": "React Query",
    "@tanstack/query-core": "TanStack Query",
    "swr": "SWR",
    "trpc": "tRPC",
    "@trpc/server": "tRPC",
    "@trpc/client": "tRPC",
    # Validation
    "zod": "Zod",
    "yup": "Yup",
    "joi": "Joi",
    "valibot": "Valibot",
    "superstruct": "Superstruct",
    "class-validator": "class-validator",
    "class-transformer": "class-transformer",
    # Utilities
    "lodash": "Lodash",
    "underscore": "Underscore",
    "ramda": "Ramda",
    "date-fns": "date-fns",
    "dayjs": "Day.js",
    "moment": "Moment.js",
    "uuid": "UUID",
    "nanoid": "Nano ID",
    "commander": "Commander.js",
    "yargs": "Yargs",
    "minimist": "minimist",
    "dotenv": "dotenv",
    "cross-env": "cross-env",
    "concurrently": "concurrently",
    "nodemon": "Nodemon",
    "pm2": "PM2",
    # Documentation
    "storybook": "Storybook",
    "@storybook/react": "Storybook",
    "typedoc": "TypeDoc",
    "docusaurus": "Docusaurus",
    "@docusaurus/core": "Docusaurus",
    # Monorepo tools
    "nx": "Nx",
    "@nx/devkit": "Nx",
    "turborepo": "Turborepo",
    "@turbo/workspaces": "Turborepo",
    "lerna": "Lerna",
    "changesets": "Changesets",
    "@changesets/cli": "Changesets",
    "pnpm": "pnpm workspaces",
    "yarn": "Yarn workspaces",
    "npm": "npm workspaces",
    # Extension development
    "vscode": "VS Code API",
    "@types/vscode": "VS Code API Types",
    # AI/ML
    "openai": "OpenAI",
    "@anthropic-ai/sdk": "Anthropic",
    "langchain": "LangChain",
    "@langchain/core": "LangChain",
    "ai": "Vercel AI SDK",
    "@vercel/ai": "Vercel AI SDK",
}

# Framework mapping for Java dependencies
JAVA_FRAMEWORK_MAP: dict[str, str] = {
    "spring-boot-starter": "Spring Boot",
    "spring-boot": "Spring Boot",
    "spring-core": "Spring",
    "spring-web": "Spring Web",
    "springmvc": "Spring MVC",
    "micronaut": "Micronaut",
    "quarkus": "Quarkus",
}

# Framework mapping for .NET dependencies (package id fragments)
DOTNET_FRAMEWORK_MAP: dict[str, str] = {
    "microsoft.aspnetcore": ".NET ASP.NET Core",
    "aspnetcore": ".NET ASP.NET Core",
    "entityframework": "Entity Framework",
    "efcore": "Entity Framework Core",
    "serilog": "Serilog",
    "nlog": "NLog",
}

# Framework mapping for Go modules
GO_FRAMEWORK_MAP: dict[str, str] = {
    "github.com/gin-gonic/gin": "Gin",
    "github.com/labstack/echo": "Echo",
    "github.com/gofiber/fiber": "Fiber",
    "github.com/gorilla/mux": "Gorilla Mux",
    "github.com/grpc/grpc-go": "gRPC",
}

# Framework mapping for PHP/composer dependencies
PHP_FRAMEWORK_MAP: dict[str, str] = {
    "laravel/framework": "Laravel",
    "symfony/symfony": "Symfony",
    "cakephp/cakephp": "CakePHP",
    "codeigniter4/framework": "CodeIgniter",
    "slim/slim": "Slim",
}

# Framework mapping for Ruby/Gemfile dependencies
RUBY_FRAMEWORK_MAP: dict[str, str] = {
    "rails": "Rails",
    "sinatra": "Sinatra",
    "hanami": "Hanami",
}

# Framework mapping for Rust/Cargo dependencies
RUST_FRAMEWORK_MAP: dict[str, str] = {
    "actix-web": "Actix Web",
    "rocket": "Rocket",
    "axum": "Axum",
    "warp": "Warp",
    "tokio": "Tokio",
}

# Mobile detection markers
ANDROID_MARKERS = [
    "AndroidManifest.xml",
    "gradle.properties",
    "app/build.gradle",
    "app/build.gradle.kts",
]
IOS_MARKERS = ["Podfile", "Podfile.lock", "Cartfile"]

# Infra markers
DOCKER_FILES = [
    "Dockerfile",
    "Dockerfile.dev",
    "Dockerfile.prod",
    "docker-compose.yml",
    "docker-compose.yaml",
    "docker-compose.dev.yml",
    "docker-compose.prod.yml",
]
K8S_HINTS = ["k8s", "kubernetes", "helm", "manifests", "charts"]

# Package managers
PACKAGE_MANAGER_HINTS = {
    "package.json": "npm",
    "npm": "npm",
    "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm",
    "package-lock.json": "npm",
    "requirements.txt": "pip",
    "pyproject.toml": "poetry/pdm/setuptools",
    "setup.py": "setuptools",
    "Pipfile": "pipenv",
    "poetry.lock": "poetry",
    "composer.lock": "composer",
    "composer.json": "composer",
    "Gemfile": "bundler",
    "Gemfile.lock": "bundler",
    "go.mod": "go modules",
    "Cargo.lock": "cargo",
    "Cargo.toml": "cargo",
    "package.swift": "swiftpm",
    "Podfile": "cocoapods",
    "Podfile.lock": "cocoapods",
    "gradle.properties": "gradle",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
}


def _normalize_package_name(name: str) -> str:
    """Normalize package name by replacing underscores/hyphens and lowercasing."""
    return name.lower().replace("-", "").replace("_", "").replace(".", "")


def _match_framework(package_name: str, framework_map: dict[str, str]) -> str | None:
    """Match a package name against the framework map."""
    normalized = _normalize_package_name(package_name)

    # Direct lookup
    if package_name.lower() in framework_map:
        return framework_map[package_name.lower()]

    # Try normalized lookup
    for key, value in framework_map.items():
        if _normalize_package_name(key) == normalized:
            return value
        # Check if package starts with key (for scoped packages like @org/name)
        if package_name.lower().startswith(key + "-") or package_name.lower().startswith(key + "/"):
            return value

    return None


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _detect_package_manager(root_path: Path) -> list[str]:
    detected: list[str] = []
    for fname, label in PACKAGE_MANAGER_HINTS.items():
        if (root_path / fname).exists():
            detected.append(label)
    return sorted(set(detected))


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _detect_java(root_path: Path) -> dict[str, Any] | None:
    pom = root_path / "pom.xml"
    gradle = root_path / "build.gradle"
    gradle_kts = root_path / "build.gradle.kts"
    frameworks: set[str] = set()
    build_tool: str | None = None

    def _scan_deps(text: str) -> None:
        for match in re.findall(r"groupId>[^<]+<|artifactId>[^<]+<", text):
            pkg = (
                match.strip("<>").split(":")[-1].replace("groupId>", "").replace("artifactId>", "")
            )
            fw = _match_framework(pkg, JAVA_FRAMEWORK_MAP)
            if fw:
                frameworks.add(fw)

    if pom.exists():
        build_tool = "Maven"
        _scan_deps(_safe_read(pom))

    for gfile, label in ((gradle, "Gradle"), (gradle_kts, "Gradle")):
        if gfile.exists():
            build_tool = build_tool or label
            text = _safe_read(gfile)
            for match in re.findall(r"['\"]([\w.-]+):([\w.-]+)['\"]", text):
                pkg = match[1]
                fw = _match_framework(pkg, JAVA_FRAMEWORK_MAP)
                if fw:
                    frameworks.add(fw)

    if frameworks or build_tool:
        return {
            "language": "Java",
            "frameworks": sorted(frameworks),
            "build_tool": build_tool or "unknown",
        }
    return None


def _detect_dotnet(root_path: Path) -> dict[str, Any] | None:
    csprojs = list(root_path.glob("*.csproj"))
    if not csprojs:
        csprojs = list(root_path.rglob("*.csproj"))
    frameworks: set[str] = set()
    for csproj in csprojs:
        text = _safe_read(csproj)
        for match in re.findall(r"<PackageReference[^>]*Include=\"([^\"]+)\"", text):
            pkg = match.lower()
            fw = _match_framework(pkg, DOTNET_FRAMEWORK_MAP)
            if fw:
                frameworks.add(fw)
    if csprojs:
        return {
            "language": ".NET",
            "frameworks": sorted(frameworks),
            "build_tool": "dotnet",
        }
    return None


def _detect_go(root_path: Path) -> dict[str, Any] | None:
    go_mod = root_path / "go.mod"
    if not go_mod.exists():
        return None
    text = _safe_read(go_mod)
    frameworks: set[str] = set()
    for match in re.findall(r"require\s+([\w./-]+)\s", text):
        fw = _match_framework(match.strip(), GO_FRAMEWORK_MAP)
        if fw:
            frameworks.add(fw)
    return {
        "language": "Go",
        "frameworks": sorted(frameworks),
        "build_tool": "go modules",
    }


def _detect_php(root_path: Path) -> dict[str, Any] | None:
    composer = root_path / "composer.json"
    if not composer.exists():
        return None
    frameworks: set[str] = set()
    try:
        data = json.loads(_safe_read(composer) or "{}")
        for dep_name in list(data.get("require", {}).keys()) + list(
            data.get("require-dev", {}).keys()
        ):
            fw = _match_framework(dep_name, PHP_FRAMEWORK_MAP)
            if fw:
                frameworks.add(fw)
    except Exception:
        pass
    return {
        "language": "PHP",
        "frameworks": sorted(frameworks),
        "build_tool": "composer",
    }


def _detect_ruby(root_path: Path) -> dict[str, Any] | None:
    gemfile = root_path / "Gemfile"
    if not gemfile.exists():
        return None
    text = _safe_read(gemfile)
    frameworks: set[str] = set()
    for match in re.findall(r"gem\s+['\"]([^'\"]+)['\"]", text):
        fw = _match_framework(match, RUBY_FRAMEWORK_MAP)
        if fw:
            frameworks.add(fw)
    return {
        "language": "Ruby",
        "frameworks": sorted(frameworks),
        "build_tool": "bundler",
    }


def _detect_rust(root_path: Path) -> dict[str, Any] | None:
    cargo = root_path / "Cargo.toml"
    if not cargo.exists():
        return None
    try:
        data = parse_cargo_toml_file(cargo)
        frameworks: set[str] = set()
        for dep_name in data.get("dependencies", []):
            fw = _match_framework(dep_name, RUST_FRAMEWORK_MAP)
            if fw:
                frameworks.add(fw)
        for dep_name in data.get("dev_dependencies", []):
            fw = _match_framework(dep_name, RUST_FRAMEWORK_MAP)
            if fw:
                frameworks.add(fw)
        for dep_name in data.get("build_dependencies", []):
            fw = _match_framework(dep_name, RUST_FRAMEWORK_MAP)
            if fw:
                frameworks.add(fw)
        return {
            "language": "Rust",
            "frameworks": sorted(frameworks),
            "build_tool": "cargo",
        }
    except Exception:
        return {
            "language": "Rust",
            "frameworks": [],
            "build_tool": "cargo",
        }


def _detect_mobile(root_path: Path) -> dict[str, Any] | None:
    android = any((root_path / p).exists() for p in ANDROID_MARKERS)
    ios = any((root_path / p).exists() for p in IOS_MARKERS)
    if not android and not ios:
        return None
    frameworks: list[str] = []
    if android:
        frameworks.append("Android")
    if ios:
        frameworks.append("iOS")
    return {
        "language": "Mobile",
        "frameworks": frameworks,
        "build_tool": "gradle/cocoapods",
    }


def _detect_infra(root_path: Path) -> list[str]:
    infra: set[str] = set()
    for fname in DOCKER_FILES:
        if (root_path / fname).exists():
            infra.add("docker")
    for hint in K8S_HINTS:
        if any(hint in str(p) for p in root_path.rglob("*")):
            infra.add("k8s")
            break
    return sorted(infra)


def _extract_python_version_from_requires_python(requires_python: str) -> str:
    """Extract Python version from requires-python specifier."""
    if not requires_python:
        return "Python"

    # Handle common patterns like ">=3.12", "^3.12", "~3.12", "3.12"
    import re

    # Look for version patterns
    match = re.search(r"(\d+\.\d+)(?:\.\d+)?", requires_python)
    if match:
        return f"Python {match.group(1)}"

    return "Python"


def _detect_build_tool(pyproject_data: dict[str, Any]) -> str | None:
    """Detect build tool from pyproject.toml data."""
    build_system = pyproject_data.get("build-system", {})
    build_backend = build_system.get("build-backend", "")

    if "poetry" in build_backend:
        return "Poetry"
    elif "flit" in build_backend:
        return "Flit"
    elif "hatchling" in build_backend:
        return "Hatchling"
    elif "pdm" in build_backend:
        return "PDM"
    elif "setuptools" in build_backend:
        return "Setuptools"
    elif "maturin" in build_backend:
        return "Maturin"

    # Check for tool-specific sections
    tool = pyproject_data.get("tool", {})
    if "poetry" in tool:
        return "Poetry"
    if "pdm" in tool:
        return "PDM"
    if "hatch" in tool:
        return "Hatchling"
    if "flit" in tool:
        return "Flit"

    return None


def detect_python_stack(root_dir: str | Path) -> dict[str, Any] | None:
    """
    Detect Python stack from project configuration files.

    Parses pyproject.toml, requirements.txt, and setup.py to identify
    frameworks, build tools, and Python version.

    Uses consolidated dependency parsing from backend.utils.dependencies
    to avoid code duplication.

    Args:
        root_dir: Path to the project root directory.

    Returns:
        Dictionary with language, frameworks, build_tool, and python_version
        or None if no Python project detected.
    """
    root_path = Path(root_dir).resolve()
    frameworks: set[str] = set()
    build_tool: str | None = None
    python_version: str = "Python"

    # First check for .python-version file (extensionless Python version file)
    python_version_file = root_path / ".python-version"
    if python_version_file.exists():
        try:
            content = python_version_file.read_text().strip()
            if content:
                # .python-version typically contains a version like "3.11.4" or "3.11"
                python_version = f"Python {content}"
                logger.debug("detected_python_version_from_file", version=python_version)
        except Exception as e:
            logger.warning("Failed to read .python-version: %s", e)

    # Try pyproject.toml first using consolidated parser
    pyproject_path = root_path / "pyproject.toml"
    if pyproject_path.exists():
        try:
            pyproject_data = parse_pyproject_toml_file(pyproject_path)

            # Detect build tool from parsed data
            build_tool = pyproject_data.get("build_tool")
            if build_tool:
                build_tool = build_tool.capitalize()

            # Match all dependencies against framework map
            for dep_name in pyproject_data.get("dependencies", []):
                framework = _match_framework(dep_name, PYTHON_FRAMEWORK_MAP)
                if framework:
                    frameworks.add(framework)

            # Match dev dependencies
            for dep_name in pyproject_data.get("dev_dependencies", []):
                framework = _match_framework(dep_name, PYTHON_FRAMEWORK_MAP)
                if framework:
                    frameworks.add(framework)

            # Match optional dependencies
            for group_deps in pyproject_data.get("optional_dependencies", {}).values():
                for dep_name in group_deps:
                    framework = _match_framework(dep_name, PYTHON_FRAMEWORK_MAP)
                    if framework:
                        frameworks.add(framework)

            # Try to get Python version from requires-python (need to parse raw for this)
            try:
                import tomllib

                with open(pyproject_path, "rb") as f:
                    raw_data = tomllib.load(f)
                project = raw_data.get("project", {})
                requires_python = project.get("requires-python", "")
                if requires_python:
                    python_version = _extract_python_version_from_requires_python(requires_python)
            except Exception:
                pass

        except Exception as e:
            logger.warning("Failed to parse pyproject.toml: %s", e)

    # Try requirements.txt using consolidated parser
    requirements_path = root_path / "requirements.txt"
    if requirements_path.exists():
        try:
            deps = parse_requirements_txt_file(requirements_path)
            for dep_name in deps:
                framework = _match_framework(dep_name, PYTHON_FRAMEWORK_MAP)
                if framework:
                    frameworks.add(framework)
        except Exception as e:
            logger.warning("Failed to parse requirements.txt: %s", e)

    # Try setup.py using consolidated parser
    setup_path = root_path / "setup.py"
    if setup_path.exists():
        try:
            setup_data = parse_setup_py_file(setup_path)

            # Match dependencies
            for dep_name in setup_data.get("dependencies", []):
                framework = _match_framework(dep_name, PYTHON_FRAMEWORK_MAP)
                if framework:
                    frameworks.add(framework)

            # Try to detect Python version from python_requires
            python_requires = setup_data.get("python_requires")
            if python_requires and python_version == "Python":
                python_version = _extract_python_version_from_requires_python(python_requires)

            # If no build tool detected yet, assume setuptools
            if not build_tool:
                build_tool = "Setuptools"
        except Exception as e:
            logger.warning("Failed to parse setup.py: %s", e)

    # If we found any Python-related info, return it
    if frameworks or build_tool or python_version != "Python":
        return {
            "language": python_version,
            "frameworks": sorted(list(frameworks)),
            "build_tool": build_tool or "unknown",
        }

    # Check for any Python files to confirm it's a Python project
    ignore_spec = load_ignore_spec(root_path)
    for py_file in root_path.rglob("*.py"):
        if not is_ignored(py_file, root_path, ignore_spec):
            return {
                "language": python_version,
                "frameworks": sorted(list(frameworks)),
                "build_tool": build_tool or "unknown",
            }

    return None


def detect_node_stack(root_dir: str | Path) -> dict[str, Any] | None:
    """
    Detect Node.js stack from project configuration files.

    Parses package.json to identify frameworks and build tools.
    Uses consolidated dependency parsing from backend.utils.dependencies.

    Args:
        root_dir: Path to the project root directory.

    Returns:
        Dictionary with language, frameworks, build_tool, and package_manager
        or None if no Node.js project detected.
    """
    root_path = Path(root_dir).resolve()
    frameworks: set[str] = set()
    node_version: str = "Node.js"

    # Look for package.json
    package_json_path = root_path / "package.json"
    if not package_json_path.exists():
        return None

    try:
        # Use consolidated parser which also detects package manager
        pkg_data = parse_package_json_file(package_json_path)
        package_manager = pkg_data.get("package_manager")
        if not package_manager:
            pkg_mgrs = _detect_package_manager(root_path)
            package_manager = pkg_mgrs[0] if pkg_mgrs else None

        # Parse engines for Node version (need raw JSON for this)
        try:
            with open(package_json_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            engines = raw_data.get("engines", {})
            node_engine = engines.get("node", "")
            if node_engine:
                import re

                match = re.search(r"(\d+(?:\.\d+)?)", node_engine)
                if match:
                    node_version = f"Node.js {match.group(1)}"
        except Exception:
            pass

        # Match dependencies against framework map
        for dep_name in pkg_data.get("dependencies", {}).keys():
            framework = _match_framework(dep_name, NODE_FRAMEWORK_MAP)
            if framework:
                frameworks.add(framework)

        # Match devDependencies
        for dep_name in pkg_data.get("dev_dependencies", {}).keys():
            framework = _match_framework(dep_name, NODE_FRAMEWORK_MAP)
            if framework:
                frameworks.add(framework)

        return {
            "language": node_version,
            "frameworks": sorted(list(frameworks)),
            "build_tool": package_manager or "npm",
        }

    except Exception as e:
        logger.warning("Failed to parse package.json: %s", e)
        return None


def _find_all_node_stacks(root_path: Path) -> list[dict[str, Any]]:
    """Find all Node.js stacks in the project, including subdirectories."""
    stacks = []

    # Check root first
    root_stack = detect_node_stack(root_path)
    if root_stack:
        stacks.append(root_stack)

    # Check immediate subdirectories for package.json
    for subdir in root_path.iterdir():
        if subdir.is_dir() and not subdir.name.startswith("."):
            # Skip common non-project directories
            if subdir.name in ("node_modules", "venv", ".venv", "__pycache__", "dist", "build"):
                continue
            subdir_stack = detect_node_stack(subdir)
            if subdir_stack:
                stacks.append(subdir_stack)

    return stacks


def detect_stack(root_dir: str | Path) -> dict[str, Any]:
    """
    Detect project stack from configuration files.

    Attempts to detect multiple stacks (Python, Node.js, Java, .NET, Go, PHP,
    Ruby, Rust, Mobile) and infra/package-manager hints, combining all
    detected information into a single stack identity.

    Args:
        root_dir: Path to the project root directory.

    Returns:
        Dictionary with languages, frameworks, build_tools, package_managers, infra.
        Returns minimal info if no stack detected.
    """
    root_path = Path(root_dir).resolve()

    detections: list[dict[str, Any]] = []

    python_stack = detect_python_stack(root_path)
    if python_stack:
        detections.append(python_stack)

    node_stacks = _find_all_node_stacks(root_path)
    detections.extend(node_stacks)

    java_stack = _detect_java(root_path)
    if java_stack:
        detections.append(java_stack)

    dotnet_stack = _detect_dotnet(root_path)
    if dotnet_stack:
        detections.append(dotnet_stack)

    go_stack = _detect_go(root_path)
    if go_stack:
        detections.append(go_stack)

    php_stack = _detect_php(root_path)
    if php_stack:
        detections.append(php_stack)

    ruby_stack = _detect_ruby(root_path)
    if ruby_stack:
        detections.append(ruby_stack)

    rust_stack = _detect_rust(root_path)
    if rust_stack:
        detections.append(rust_stack)

    mobile_stack = _detect_mobile(root_path)
    if mobile_stack:
        detections.append(mobile_stack)

    languages: list[str] = []
    frameworks: set[str] = set()
    build_tools: list[str] = []

    for d in detections:
        if d.get("language"):
            languages.append(d["language"])
        frameworks.update(d.get("frameworks", []))
        bt = d.get("build_tool")
        if bt:
            build_tools.append(bt)

    pkg_mgrs = _detect_package_manager(root_path)
    infra = _detect_infra(root_path)

    # Check for special extensionless files and add their indicators
    _detect_special_files(root_path, languages, frameworks, build_tools)

    if languages or pkg_mgrs or infra:
        languages = _dedupe_preserve_order(languages)
        build_tools = _dedupe_preserve_order([bt for bt in build_tools if bt and bt != "unknown"])
        return {
            "languages": languages or ["Unknown"],
            "frameworks": sorted(list(frameworks)),
            "build_tools": build_tools if build_tools else ["unknown"],
            "package_managers": pkg_mgrs,
            "infra": infra,
        }

    return {
        "languages": ["Unknown"],
        "frameworks": [],
        "build_tools": ["unknown"],
        "package_managers": [],
        "infra": [],
    }


def _detect_special_files(
    root_path: Path,
    languages: list[str],
    frameworks: set[str],
    build_tools: list[str],
) -> None:
    """
    Detect special extensionless files and add their indicators to the stack.

    This handles files like Makefile, Dockerfile, .env, etc.

    Args:
        root_path: Path to the project root directory
        languages: List to append detected languages to
        frameworks: Set to add detected frameworks to
        build_tools: List to append detected build tools to
    """
    # Check for Makefile
    makefile_patterns = ["Makefile", "makefile", "GNUmakefile"]
    for pattern in makefile_patterns:
        if (root_path / pattern).exists():
            build_tools.append("Make")
            logger.debug("detected_makefile", pattern=pattern)
            break

    # Check for Dockerfile
    dockerfile_patterns = ["Dockerfile", "Dockerfile.dev", "Dockerfile.prod", "Dockerfile.test"]
    for pattern in dockerfile_patterns:
        if (root_path / pattern).exists():
            frameworks.add("Docker")
            logger.debug("detected_dockerfile", pattern=pattern)
            break

    # Check for docker-compose
    docker_compose_patterns = [
        "docker-compose.yml",
        "docker-compose.yaml",
        "docker-compose.dev.yml",
        "docker-compose.prod.yml",
    ]
    for pattern in docker_compose_patterns:
        if (root_path / pattern).exists():
            frameworks.add("Docker Compose")
            logger.debug("detected_docker_compose", pattern=pattern)
            break

    # Check for .env files
    env_patterns = [
        ".env",
        ".env.local",
        ".env.dev",
        ".env.development",
        ".env.test",
        ".env.production",
        ".env.prod",
    ]
    for pattern in env_patterns:
        if (root_path / pattern).exists():
            frameworks.add("Environment Variables")
            logger.debug("detected_env_file", pattern=pattern)
            break

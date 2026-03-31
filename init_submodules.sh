#!/bin/bash
set -e

# Python (Already done but left for safety)
git submodule add -f https://github.com/tiangolo/fastapi.git tests/benchmark/fixtures/python || true
cd tests/benchmark/fixtures/python && git checkout 0.110.0 && cd ../../../.. || git stash

# TypeScript
git submodule add -f --depth 1 https://github.com/vercel/next.js.git tests/benchmark/fixtures/typescript || true
cd tests/benchmark/fixtures/typescript && git fetch origin tag v14.2.3 --depth 1 && git checkout v14.2.3 && cd ../../../..

# Go
git submodule add -f --depth 1 https://github.com/kubernetes/kubernetes.git tests/benchmark/fixtures/go || true
cd tests/benchmark/fixtures/go && git fetch origin tag v1.29.3 --depth 1 && git checkout v1.29.3 && cd ../../../..

# Rust
git submodule add -f --depth 1 https://github.com/tokio-rs/tokio.git tests/benchmark/fixtures/rust || true
cd tests/benchmark/fixtures/rust && git fetch origin tag tokio-1.37.0 --depth 1 && git checkout tokio-1.37.0 && cd ../../../..

# Java
git submodule add -f --depth 1 https://github.com/spring-projects/spring-boot.git tests/benchmark/fixtures/java || true
cd tests/benchmark/fixtures/java && git fetch origin tag v3.2.4 --depth 1 && git checkout v3.2.4 && cd ../../../..

# C++
git submodule add -f --depth 1 https://github.com/llvm/llvm-project.git tests/benchmark/fixtures/cpp || true
cd tests/benchmark/fixtures/cpp && git fetch origin tag llvmorg-18.1.3 --depth 1 && git checkout llvmorg-18.1.3 && cd ../../../..

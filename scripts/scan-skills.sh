#!/bin/sh
set -eu
# Install separately: uv tool install 'git+https://github.com/NVIDIA/SkillSpector.git'
# Static scan avoids sending skill contents to an LLM provider.
exec skillspector scan ./skills --recursive --no-llm

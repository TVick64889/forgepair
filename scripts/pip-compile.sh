#!/bin/bash

# exit when any command fails
set -e

# Add verbosity flag to see more details about dependency resolution
VERBOSITY="-v"  # Use -v for less detail, -vvv for even more detail

# First compile the common constraints of the full requirement suite
# to make sure that all versions are mutually consistent across files.
# --universal resolves for the full Python version support matrix at
# once (rather than whichever single interpreter runs this script), so
# that python-compat.in's version-branched numpy/scipy constraints
# survive the compile instead of collapsing to one pinned version
# that's incompatible with older supported Pythons (see
# https://github.com/TVick64889/forgepair/issues/18). --universal on
# its own only resolves from whatever interpreter is currently active
# upward, so --python-version pins the floor to match pyproject.toml's
# requires-python lower bound, covering the full matrix.
uv pip compile \
    $VERBOSITY \
    --universal \
    --python-version 3.10 \
    --no-strip-extras \
    --output-file=requirements/common-constraints.txt \
    requirements/requirements.in \
    requirements/requirements-*.in \
    $1

# Compile the base requirements
uv pip compile \
    $VERBOSITY \
    --universal \
    --python-version 3.10 \
    --no-strip-extras \
    --constraint=requirements/common-constraints.txt \
    --output-file=requirements.txt \
    requirements/requirements.in \
    $1

# Compile additional requirements files
SUFFIXES=(dev help browser playwright)

for SUFFIX in "${SUFFIXES[@]}"; do
    uv pip compile \
        $VERBOSITY \
        --universal \
        --python-version 3.10 \
        --no-strip-extras \
        --constraint=requirements/common-constraints.txt \
        --output-file=requirements/requirements-${SUFFIX}.txt \
        requirements/requirements-${SUFFIX}.in \
        $1
done

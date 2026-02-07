#!/usr/bin/env bash

# Wrapper that runs tests/runTests.sh against both distribution scripts.
# Usage: ./runTests.sh [-v]

cd "$(dirname "$0")/tests" || exit

err=0
for script in ../distribution ../distribution.py; do
    if [ -x "$script" ]; then
        echo "=== Testing: $script ==="
        distribution="$script" ./runTests.sh "$@" || err=1
    fi
done

exit $err

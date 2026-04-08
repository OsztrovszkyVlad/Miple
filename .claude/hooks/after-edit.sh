#!/bin/bash
# Auto-format after every file edit
if [[ "$1" == *.py ]]; then
  black "$1" 2>/dev/null
  echo "formatted $1"
fi
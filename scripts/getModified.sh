#!/bin/bash

echo "$(git status | grep -o "modified:\s\+\S\+" | grep -o "\s\S\+")"

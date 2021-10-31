#!/bin/bash
python3 -c "text = open('loserMessages.txt').read().split('\n'); text.sort(); print('\n'.join(text))"

#!/bin/bash
git config --global user.email "billybrickner@gmail.com"
git config --global user.name "Billy Brickner"
git config credential.helper 'cache --timeout=30000'
git config --global core.editor "vim"
git config pull.rebase false

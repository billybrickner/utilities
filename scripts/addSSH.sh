#!/bin/bash

ssh-keygen -t ed25519 -C "billybrickner@gmail.com"
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
ssh-keyscan -t rsa github.com >> ~/.ssh/known_hosts
cat ~/.ssh/id_ed25519.pub


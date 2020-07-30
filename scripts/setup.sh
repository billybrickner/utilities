#!/bin/bash
PATH_TO_PROFILES=~/utilities/profile
pushd ~
echo ". $PATH_TO_PROFILES/.my_bash_profile.sh" >> .bashrc
mkdir .vim
pushd .vim
mkdir spell
popd
pushd .cache
mkdir vim
popd
cp $PATH_TO_PROFILES/.vimrc .
source .bashrc
popd
gitSetup.sh

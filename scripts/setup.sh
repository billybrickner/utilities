#!/bin/bash
PATH_TO_PROFILES=~/utilities/profiles
pushd ~
echo ". $PATH_TO_PROFILES/.my_bash_profile.sh" >> .bashrc
mkdir ".vim"
pushd .vim && mkdir spell && popd
mkdir cache && pushd .cache && mkdir vim && popd
cp $PATH_TO_PROFILES/.vimrc .
source .bashrc
popd
gitSetup.sh

#!/bin/bash
PATH_TO_PROFILES=~/utilities/profiles
pushd ~
echo ". $PATH_TO_PROFILES/.my_bash_profile.sh" >> .bashrc
mkdir ".vim"
pushd ".vim" && mkdir spell && popd
mkdir ".cache" && pushd ".cache" && mkdir vim && popd
cp $PATH_TO_PROFILES/.vimrc .
popd
echo "Now run:"
echo "pushd ~"
echo "source .bashrc"
echo "pushd utilities"
echo "gitSetup.sh"
echo "popd && popd"

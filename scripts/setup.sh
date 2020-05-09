#!/bin/bash
pushd ~
echo '. ~/utilities/.my_bash_profile.sh' >> .bashrc
mkdir .vim
cd .vim
mkdir spell
cd ../
cd .cache
mkdir vim
cd ../
cp utilities/.vimrc .
source .bashrc
gitSetup.sh
popd

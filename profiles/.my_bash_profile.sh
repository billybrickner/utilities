# To add this to bash profile, copy the following: . ~/utilities/profiles/.my_bash_profile.sh

# Pull the branch name out of a git branch
parse_git_branch() {
     git branch 2> /dev/null | sed -e '/^[^*]/d' -e 's/* \(.*\)/ (\1)/'
}

# Update Path
export PS1="\u@\h \[\033[32m\]\w\[\033[33m\]\$(parse_git_branch)\[\033[00m\] \n$ "

# Capture any vimrc changes so that I can update my config upon startup
cp ~/.vimrc ~/utilities/profiles

# Add scripts to PATH
export PATH="$PATH:$HOME/utilities/scripts"

# qemu alias since this is an x86-64 system
alias qemu=qemu-system-x86_64

# Get Julia to work
export LD_LIBRARY_PATH="/usr/lib/wsl/lib/:"
export JULIA_NUM_THREADS=16

export PYENV_ROOT="$HOME/.pyenv"
command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"

eval "$(pyenv virtualenv-init -)"

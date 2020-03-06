# To add this to bash profile, copy the following: . ~/utilities/.my_bash_profile.sh

# Pull the branch name out of a git branch
parse_git_branch() {
     git branch 2> /dev/null | sed -e '/^[^*]/d' -e 's/* \(.*\)/ (\1)/'
}

# Update Path
export PS1="\u@\h \[\033[32m\]\w\[\033[33m\]\$(parse_git_branch)\[\033[00m\] $ "

# Capture any vimrc changes so that I can update my config upon startup
cp ~/.vimrc ~/utilities

# Add scripts to PATH
export PATH="$PATH:$HOME/utilities/scripts"

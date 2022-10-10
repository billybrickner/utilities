# To add this to bash profile, copy the following: . ~/utilities/profiles/.my_bash_profile.sh

# Pull the branch name out of a git branch
parse_git_branch() {
     git branch 2> /dev/null | sed -e '/^[^*]/d' -e 's/* \(.*\)/ (\1)/'
}

# Add a timer to the last command
function timer_start {
    timer=${timer:-$SECONDS}
}

function timer_stop {
    timer_show=$(($SECONDS - $timer))
    unset timer

    if [ $timer_show -gt 5 ]; then
        last_command=$(HISTTIMEFORMAT='' history 1 | sed 's/ *[0-9]* *//')
        last_command_title=$(echo "$last_command" | cut -d " " -f1)
        terminal-notifier -message "$last_command" -title  "$last_command_title done in ${timer_show}s" -sound default -ignoreDnD
    fi
}

trap 'timer_start' DEBUG

if [ "$PROMPT_COMMAND" == "" ]; then
    PROMPT_COMMAND="timer_stop"
else
    PROMPT_COMMAND="$PROMPT_COMMAND; timer_stop"
fi

# Update Path
export PS1="\[\033[32m\]\W\[\033[33m\]\$(parse_git_branch)\[\033[00m\] \u@\h \[\033[34m\]\w\[\033[00m\]
$ "

# Capture any vimrc changes so that I can update my config upon startup
cp ~/.vimrc ~/utilities/profiles

# Add scripts to PATH
export PATH="$PATH:$HOME/utilities/scripts:$HOME/utilities/scripts/local"

# qemu alias since this is an x86-64 system
alias qemu=qemu-system-x86_64

# Spelling suggestions
shopt -s cdspell

#Avoid duplicates
HISTCONTROL=erasedups
# When the shell exits, append to the history file instead of overwriting it
shopt -s histappend

# After each command, append to the history file and reread it
PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND$'\n'}history -a; history -c; history -r"

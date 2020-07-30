# Update all git repositories in a subdirectory
git_branch() {
    git branch 2> /dev/null | sed -e '/^[^*]/d' -e 's/* \(.*\)/\1/'
}
update_in_curr_dir() {
    git pull origin master
    git pull upstream master && git pull upstream master
    git push origin master
}

for D in */; do
    echo "Updating $D"
    pushd $D > /dev/null
    git fetch
    git fetch upstream
    if [ $(git_branch) = 'master' ]; then
        update_in_curr_dir
    fi
    popd > /dev/null
done
addTags.sh

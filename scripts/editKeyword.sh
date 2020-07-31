git grep -n $1
echo "Edit [Y/N]"
read conf
if [ $conf == Y -o $conf == y ]
then
    vim -c "$(git grep -n $1 | sed -e 's/^\([^:]\+\):\([0-9]\+\).\+$/:e \1|:2/g')"
fi

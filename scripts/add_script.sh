# This is a script to add the last N commands to a script for future usage
# Optional input $1 - N (the last N commands)
PATH_TO_SCRIPTS=$HOME/utilities/scripts
# Get the -n command executed 
# Regex to remove leading and trailing whitespace
# Regex to replace eval characters with escape character
# Use doubel quotes because we want to capture literals
N=2 # Number of lines to go back in history. i
    # Default 2 because we want to exclude N=1 which should be
    # running this script
last_command() {
    fc -l -n -$N -$N | sed -e 's/\s*\(\w[^\n]*\w\)\s*$/\1/g' -e 's/\([$"]\)/\\\1/g' 
}

# Echo last command to be able to load script into file
# By not writing the script directly to a file there is a chance
# to inspect the script before putting it in a file
echo_last_command(){
    lstCMD="$(last_command)"
    echo "echo \"$lstCMD\" >> "$scriptName
}



echo "Enter script name: "
read scriptName
scriptName=$PATH_TO_SCRIPTS/$scriptName.sh
if [ -z $1 ]
    then
        numCommands=1
    else
        numCommands=$1
fi
echo "echo '#!/bin/bash' >" $scriptName
# Stop at 2 to exclude running this command from the script
for (( i=$numCommands+1; i>1; i-- ))
do
    N=$i
    echo_last_command
done
# Make the script executable
echo 'chmod +x '$scriptName

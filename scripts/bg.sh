#!/bin/bash
if [ -f "/tmp/$1.log" ]; then
    rm /tmp/$1.log
fi 
$@ > /tmp/$1.log 2>&1 &

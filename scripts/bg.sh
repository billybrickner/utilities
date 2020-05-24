#!/bin/bash
rm /tmp/$1.log
$@ > /tmp/$1.log 2>&1 &

#!/bin/sh

echo 'Backing up config file'
cp config.ini config.ini.bak

echo 'Resetting git repo to known state'
git reset --hard

echo 'Pulling main'
git pull oriign main

echo 'Restoring config file'
cp config.ini.bak config.ini

echo 'starting mctomqtt.py'
python3 mctomqtt.py
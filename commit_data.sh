#!/bin/sh

git commit data/hourly_history.csv -m 'updated data'
sleep 0.1
git push

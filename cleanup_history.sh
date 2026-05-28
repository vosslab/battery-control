#!/bin/sh


echo "note this puts the header at the end, instead of the start"

cat data/hourly_history.csv | sort | grep -v STARTUP | uniq -w 20 > hourly_history.csv

wc -l hourly_history.csv data/hourly_history.csv

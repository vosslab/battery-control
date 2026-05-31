#!/bin/sh

set -e

DATA_FILE="data/hourly_history.csv"

added_lines=$(git diff HEAD --numstat -- "$DATA_FILE" | awk '{print $1}')

if [ -z "$added_lines" ]; then
	echo "No data changes to commit."
	exit 0
fi

latest_hour=$(awk -F, 'END {print $1}' "$DATA_FILE")

if [ "$added_lines" = "1" ]; then
	row_label="row"
else
	row_label="rows"
fi

commit_message="Add $added_lines hourly data $row_label through $latest_hour"

git commit "$DATA_FILE" -m "$commit_message"
sleep 0.1
git push --quiet

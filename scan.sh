#!/bin/sh

status_code=0
attempts=0

while [ "$status_code" -ne 200 ] && [ "$attempts" -ne 5 ];
do
  (( attempts++ ))
  status_code=$(curl -s -o response.txt -w "%{http_code}" "Dependency-scan-api.com:3000/scan/$1/$2")
  if [ status_code != "200" ]; then
    sed 's/<br>/\n/g' response.txt > output.txt
    cat output.txt
    rm response.txt
    rm output.txt
  else
    echo "got status_code, $status_code. Retrying $attempts/5"
  fi
done
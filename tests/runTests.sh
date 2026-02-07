#!/usr/bin/env bash

# make sure env is setup proper
if [ -z "$distribution" ]; then
    echo "To run tests, first export distribution=<pathToDistributionToTest>"
    exit 255
fi

getopts "v" verbose

# the tests
echo ""
printf "Running test: 1. "
cat stdin.01.txt | "$distribution" --rcfile=../distributionrc --graph --height=35 --width=120 --char=dt --color --verbose > stdout.01.actual.txt 2> stderr.01.actual.txt

printf "2. "
cat stdin.02.txt | awk '{print $4" "$5}' | "$distribution" --rcfile=../distributionrc --size=med --width=110 --tokenize=word --match=word --verbose --color > stdout.02.actual.txt 2> stderr.02.actual.txt

printf "3. "
grep modem stdin.02.txt | awk '{print $1}' | "$distribution" --rcfile=../distributionrc --width=110 --height=15 --char='|' --verbose --color 2> stderr.03.actual.txt | sort > stdout.03.actual.txt

printf "4. "
cat stdin.03.txt | "$distribution" --rcfile=../distributionrc --size=large --height=8 --width=60 --tokenize=/ --palette=0,31,33,35,37 --char='()' > stdout.04.actual.txt 2> stderr.04.actual.txt

printf "5. "
cat stdin.03.txt | "$distribution" --rcfile=../distributionrc --char=pc --width=48 --tokenize=word --match=num --size=large --verbose 2> stderr.05.actual.txt | sort -n > stdout.05.actual.txt

printf "6. "
# generate a large list of deterministic but meaningless numbers
((i = 0))
while [[ $i -lt 3141592 ]]; do
    echo $((i ^ (i += 17)))
done | cut -c 2-6 | "$distribution" --rcfile=../distributionrc --width=124 --height=29 --palette=0,32,34,36,31 --char=^ --verbose > stdout.06.actual.txt 2> stderr.06.actual.txt

printf "7. "
cat stdin.04.txt | awk '{print $8}' | "$distribution" --rcfile=../distributionrc --size=s --width=90 --char=Ξ > stdout.07.actual.txt 2> stderr.07.actual.txt

echo "done."

# be sure output is proper
err=0
printf "Comparing results: "
for i in 01 02 03 04 05 06 07; do
    printf '%s. ' "$i"
    if ! diff -w "stdout.$i.expected.txt" "stdout.$i.actual.txt"; then
        err=1
    fi

    # when in verbose mode, ignore any "runtime lines, since those may differ by
    # milliseconds from machine to machine. Also ignore any lines with "^M" markers,
    # which are line-erase signals used for updating the screen interactively, and
    # thus don't need to be stored or compared.
    if [ "$verbose" = "v" ]; then
        diff -w -I "runtime:" -I $'\r' "stderr.$i.expected.txt" "stderr.$i.actual.txt"
    fi
done

echo "done."

# clean up
rm stdout.*.actual.txt stderr.*.actual.txt

exit "$err"

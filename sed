sed 's/\([^,]*\)/'\''\1'\''/g' values.txt | sed 's/,/, /g' | sed 's/^/[ /; s/$/ ]/'

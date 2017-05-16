# Silly script for printing stuff from Markdown formatted text file.
# variable 'search' needs to be defined.

BEGIN {
    found=0
    fline=0
    level=0
    lastline=0
}

{
    if (!found && $0 ~ search) {
        #print $0, NR
        found=1
        pprev=$0
        fline=NR
    }
    if (fline > 0 && fline+1 == NR) {
        if ($1 ~ /==/) {
            level=1
            #print $0, NR, level
            prev=$0
        } else if ($1 ~ /--/) {
            level=2
            #print $0, NR, level
            prev=$0
        } else {
            found=0
            level=0
        }
    }
    else if (level > 0) {
        if ($1 ~ /==/) {
            level=0
            lastline=NR
        } else if ($1 ~ /--/ && level == 2) {
            level=0
            lastline=NR
        }

        nline=$0
        print pprev
        pprev=prev
        if (NR > fline+1) {
            prev=nline
        }
    }
}

END {
    if (found && lastline == 0) {
        print pprev
        print prev
    }
}

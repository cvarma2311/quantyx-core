#!/bin/bash

pushd "$(dirname "$(readlink -f "$0")")" >/dev/null

if [ -d "jre" ] 
then
    chmod -R 0755 jre    
    export JAVA_HOME=`pwd`/jre
    PATH=$JAVA_HOME/bin:$PATH
    java -DDENODO_JRE_HOME="`pwd`/jre" -jar denodo-install-9.dat
else 
	# -----------------------------------------------------------------------------
	#  Environment variable JAVA_HOME must be set and exported
	# -----------------------------------------------------------------------------
	
	if [ -a "$JAVA_HOME/jre/bin/java" ]
	then
	    JAVA_BIN="$JAVA_HOME/jre/bin/java"
	    JAVA_BIN_DIR="$JAVA_HOME/jre/bin"
	else
	    JAVA_BIN="$JAVA_HOME/bin/java"
	    JAVA_BIN_DIR="$JAVA_HOME/bin"
	fi
	if [ -a "$JAVA_BIN" ]
	then
		PATH=$JAVA_BIN_DIR:$PATH
	    "$JAVA_BIN" -jar "denodo-install-9.dat"
	    exit 0
	else
	    echo "Unable to execute $0: Environment variable JAVA_HOME must be set and exported"
	    exit 1
	fi
fi

popd >/dev/null


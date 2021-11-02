#!/bin/bash

sdk-assistant target list | grep "$1\.pool\." | xargs -r -n1 sdk-assistant target remove -y

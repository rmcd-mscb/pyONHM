#!/bin/bash

# Load conda environment
eval "$(conda shell.bash hook)"
conda activate pyonhm

#change directory to nhm_uc.env
cd ~/git/pyONHM || exit

# Run update CFSv2 median forecast
pyonhm run-operational --env-file nhm_uc.env
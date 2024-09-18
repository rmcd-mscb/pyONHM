#!/bin/bash

# Load conda environment
eval "$(conda shell.bash hook)"
conda activate pyonhm

#change directory to nhm_uc.env
cd ~/git/pyONHM || exit

# Run update CFSv2 median forecast
pyonhm run-update-cfsv2-data --env-file nhm_uc.env --method median

# Run update CFSv2 ensembles forecast
pyonhm run-update-cfsv2-data --env-file nhm_uc.env --method ensemble

#!/bin/bash

# Ensure HOME is set (cron may not set it)
export HOME="${HOME:-/home/$(whoami)}"

# Add Miniforge3 to PATH
export PATH="$HOME/miniforge3/bin:$PATH"

# Attempt to locate conda.sh dynamically
CONDA_BASE=$(conda info --base 2>/dev/null)

if [ -n "$CONDA_BASE" ] && [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
    source "$CONDA_BASE/etc/profile.d/conda.sh"
elif [ -f "$HOME/miniforge3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniforge3/etc/profile.d/conda.sh"
else
    echo "Conda initialization script not found."
    exit 1
fi

# Activate the conda environment
conda activate pyonhm

# Define the absolute path to nhm_uc.env
ENV_FILE="$HOME/git/pyONHM/nhm_uc.env"

# Define the log file with the date string
LOGFILE="$HOME/pyonhm_logs/pyonhm_cfsv2_cron_$(date '+%Y%m%d').log"

# Redirect all output to the log file
exec >> "$LOGFILE" 2>&1

# Run update CFSv2 median forecast
pyonhm run-update-cfsv2-data --env-file "$ENV_FILE" --method median

# Run update CFSv2 ensembles forecast
pyonhm run-update-cfsv2-data --env-file "$ENV_FILE" --method ensemble


#!/usr/bin/env python3
"""
Script Name: ncf2cbh.py

Description:
This script converts NetCDF climate data files into Custom Basin Hydrograph (CBH) format,
which is used by the PRMS hydrologic model. It processes data by mapping NetCDF variable values
to NHM IDs and writing them into CBH files for each climate variable. The script supports
operational, ensemble, and ensemble-median processing modes.

Dependencies:
- Python 3.8 or higher
- netCDF4: to interact with NetCDF files
- numpy: for numerical operations
- cyclopts: for command line interface creation and handling
- csv: for reading NHM ID mappings from CSV files

Usage:
The script is meant to be run as part of a Docker container setup, typically invoked via a
command line interface managed by cyclopts. Example usage (when run directly):

    python ncf2cbh.py <working_directory> <prefix> <nhm_id_directory> <mode> [--ensemble ENSEMBLE_NUMBER]

Where:
- <working_directory>: Directory where the NetCDF files and output CBH files are stored.
- <prefix>: Prefix used to identify specific NetCDF files.
- <nhm_id_directory>: Directory containing the NHM ID mapping file.
- <mode>: Processing mode, either 'op' (operational), 'ensemble', or 'median'.
- ENSEMBLE_NUMBER: Optional, used when mode is 'ensemble' or 'median'.

Authors:
- Richard McDonald (email@usgs.gov)
- Steven Markstrom (email@usgs.gov)
- Andrew Halper (email@usgs.gov)

Created Date: April 12, 2024
Last Modified: April 12, 2024

Additional Notes:
This script is part of the ncf2cbh Docker image and is typically not run standalone.
Ensure that all necessary environment variables are correctly set in the Docker container.
"""
from netCDF4 import Dataset  # http://code.google.com/p/netcdf4-python/
from netCDF4 import num2date
from pathlib import Path
import datetime
import os
import sys
import numpy as np
import csv

from cyclopts import App, Group, Parameter, validators

app = App()

def read(nc_fn):
    nc_fid = Dataset(nc_fn, "r")
    nc_attrs = nc_fid.ncattrs()
    # print 'attrs', nc_attrs

    nc_dims = list(nc_fid.dimensions)
    # print 'dims', nc_dims

    # Figure out the variable names with data in the ncf.
    nc_vars = list(nc_fid.variables)
    remove_list = list(nc_dims)
    remove_list.extend(["hru_lat", "hru_lon", "seg_lat", "seg_lon", "lat", "lon", "crs"])
    var_names = [e for e in nc_vars if e not in remove_list]
    # print 'var_names', var_names

    time = nc_fid.variables["time"][:]
    nts = len(time)
    # print(time, nts)

    time_var = nc_fid.variables["time"]
    # print(str(time_var))
    dtime = num2date(time_var[:], time_var.units)
    # print("dtime = " + str(dtime[0]))

    base_date_str = str(dtime[0])
    #    print('base_date_str ' + base_date_str)
    tok = base_date_str.split(" ")
    ymd = tok[0]
    tok = ymd.split("-")
    base_date = datetime.date(int(tok[0]), int(tok[1]), int(tok[2]))

    # Read the values into a dictionary.
    vals = {}
    for var in var_names:
        f1 = nc_fid.variables[var][:]
        vals[var] = f1

    nc_fid.close()

    return var_names, base_date, nts, vals


# dir is where to write the CBH files
# full path required for nc_fn
def run(dir, nc_fn, nhmid_dir):
    var_names, base_date, nts, vals = read(nc_fn)

    # read the mapping
    # nhm_id = np.zeros(114958, dtype=np.int32)
    nhm_id_list = []
    ii = 0
    nhm_id_file = f"{nhmid_dir}/nhm_id"
    # changing this to use count because for the upper colorado case,
    # the id's are ordered but begin at ~ 82000.  So we are assuming the data
    # are ordered.
    with open(nhm_id_file) as csv_file:
        csv_reader = csv.reader(csv_file, delimiter=",")
        for count, _ in enumerate(csv_reader):
            # Append each id to the list
            nhm_id_list.append(int(count))
    # Convert the list to a NumPy array
    nhm_id = np.array(nhm_id_list, dtype=np.int32)

    # Write CBH files.
    for name in var_names:
        v = vals[name]
        v2 = np.zeros(114958)
        nfeats = len(v[0])
        fn2 = dir + name + ".cbh"  # _t to separate unfilled from filled cbh file
        current_date = base_date
        print(f"writing {fn2}")
        with open(fn2, "w") as fp:
            fp.write("Written by ncf2cbh.py\n")
            fp.write(f"{name} {nfeats}" + "\n")
            fp.write("########################################\n")

            for ii in range(nts):
                fp.write(
                    f"{str(current_date.year)} {str(current_date.month)} {str(current_date.day)} 0 0 0"
                )

                for jj in range(nfeats):
                    if name == "prcp":
                        v2[jj] = v[ii, nhm_id[jj] - 1] / 25.4
                    elif name in ["tmax", "tmin"]:
                        v2[jj] = v[ii, nhm_id[jj] - 1] * 9 / 5 + 32
                    else:
                        v2[jj] = v[ii, nhm_id[jj] - 1]
                for jj in range(nfeats):
                    if name == "prcp" or name not in ["tmax", "tmin"]:
                        fp.write(" " + "{:.2f}".format(v2[jj]))
                    else:
                        fp.write(" " + "{:.1f}".format(v2[jj]))
                fp.write("\n")
                current_date += datetime.timedelta(days=1)


@app.default
def ncf2cbh(input_path: str, prefix: str, root_path: str, mode: str, ensemble: int = 0):
    """
    Function to process gridmet-etl netcdf output data based on the specified mode.

    This function performs an ETL from gridmet-etl netcdf files to chb files required by prms. It operates on both
    operational gridmet data and on cfsv2 forecast data, both the 48 ensembles and the median ensemble.

    Args:
        input_path (str): The working directory path.
        prefix (str): The prefix for the output file.
        root_path (str): The directory containing myparam.param andNHM ID file.
        mode (str): The processing mode, either "op", "ensemble", or "median".
        ensemble (int, optional): The ensemble number. Defaults to 0.

    Returns:
        None

    Raises:
        FileNotFoundError: If the specified nc_fn file does not exist.
    """
    print("in ncf2cbh")
    if mode == "ensemble":
        # Add ensemble_n folder such that each ensemble is processed in a different folder named with the ensemble
        # number suffix.
        i_path = Path(input_path) / f"ensemble_{int(ensemble)}"
        nc_fn = i_path / f"{prefix}_{int(ensemble)}.nc"
    elif mode == "median":
        nc_fn = input_path + prefix + "_median" + ".nc"
    elif mode == "op":
        nc_fn = input_path + prefix + ".nc"
    else:
        print(f"mode: {mode} not in ensemble, median, or op")

    if not os.path.exists(nc_fn):
        print(f"Error: {nc_fn} does not exist.")
        sys.exit(1)

    run(input_path, nc_fn, root_path)
def main():
    try:
        app()
    except Exception as e:
        print(e)

if __name__ == "__main__":
    sys.exit(main())





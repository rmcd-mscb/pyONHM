# Markstrom
# Wed Apr 09 09:43:53 MDT 2019
# Modified by rmcd 2024-03-19 to write full ouput, also generalized so it can be used by models 
# other than CONUS.
# Modified by rmcd 2024-04-16 with further generalizations to handle forecasted output, which requires passing 
# both working directory and path to json file explicitly. Now we don't use the path to the file in the json file,
# Rather the working directory + varname + .csv is the file path.

import itertools
from pathlib import Path
import numpy as np
import csv
import json
import datetime
import getpass
from netCDF4 import Dataset
import os
import sys
from datetime import datetime
from cyclopts import App, Group, Parameter, validators
from typing_extensions import Annotated
import argparse

app = App()
# This function copied from onhm-runners/prms_utils/csv_reader.py

# Read a PRMS "output" csv. For these files, there is a remapping in the header
# line that tells the order of the columns

def read_output(csvfn):
    # figure out the number of features (ncol - 1)
    # figure out the number of timesteps (nrow -1)
    with open(csvfn, "r") as csvfile:
        spamreader = csv.reader(csvfile)

        header = next(spamreader)
        nfeat = len(header) - 1

        ii = 0
        for row in spamreader:
            ii = ii + 1
        nts = ii

    vals = np.zeros(shape=(nts, nfeat))
    indx = np.zeros(shape=nfeat, dtype=int)
    with open(csvfn, "r") as csvfile:
        spamreader = csv.reader(csvfile)

        # Read the header line
        header = next(spamreader)
        for ii in range(1, len(header)):
            indx[ii - 1] = int(header[ii])

        # print(indx)
         # Read the CSV file values, line-by-line, column-by-column
        ii = 0
        for row in spamreader:
            jj = 0
            kk = 0
            for tok in row:
                # Now skip the date/time fields and put the values into the 2D array
                if jj > 0:
                    try:
                        vals[ii][kk] = float(tok)
                        kk = kk + 1
                    except:
                        print('read_output: ', str(tok), str(ii), str(kk), str(indx[kk]-1))
                else:
                    # Get the base date (ie date of first time step) from the first row of values
                    if ii == 0:
                        base_date = tok
                    else:
                        end_date = tok
                    # print(tok)

                jj = jj + 1
            ii = ii + 1

    return nts, nfeat, base_date, end_date, vals


def read_feature_georef(dir: Path, name: str):
    # for reasons unknown, feature_georef.*.file values are prefixed with ".//",
    # hence [2:] below
    # fn1 = (cntl["feature_georef"][name]["file"])[2:]
    fn1 = dir / f"{name}.csv"
    # fn1 = f"{name}.csv"

    nfeat = sum(1 for _ in open(fn1))
    vals = np.zeros(shape=(nfeat))
    with open(fn1, "r") as csvfile:
        spamreader = csv.reader(csvfile)
        ii = 0
        for row in spamreader:
            vals[ii] = float(row[0])
            ii = ii + 1
    return vals

def read_param_values(dir, field):
    filename = Path(dir) / "myparam.param"
    values = []  # List to store the elevation values
    start_collecting = False  # Flag to start collecting values
    count_values = 0  # To count the values read
    
    with open(filename, 'r') as file:
        for line in file:
            stripped_line = line.strip()  # Remove any leading/trailing whitespace
            
            if stripped_line == field:
                # Skip the next four lines after 'hru_elev'
                for _ in range(4):
                    next(file)
                start_collecting = True  # Set flag to start collecting after skipping
                continue
            
            if stripped_line == '####' and start_collecting:
                break  # Stop reading if we hit #### after starting to collect
            
            if start_collecting:
                try:
                    # Convert the line to a float and add to the list
                    value = float(stripped_line)
                    values.append(value)
                    count_values += 1
                except ValueError:
                    continue  # If conversion fails, skip the line
        print(f"Read {count_values} {field} values")
    return np.array(values)

def write_variable_block(cntl, ncf, name):
    v1 = ncf.createVariable(
        name,
        np.float64,
        (cntl["feature_georef"][name]["dimid"]),
        fill_value=float(cntl["feature_georef"][name]["fill_value"]),
    )
    v1.long_name = cntl["feature_georef"][name]["long_name"]
    v1.standard_name = cntl["feature_georef"][name]["standard_name"]
    v1.units = cntl["feature_georef"][name]["units"]
    return v1


def write_timeseries_block(cntl, ncf, name):
    v1 = ncf.createVariable(
        name,
        np.float64,
        ("time", cntl["output_variables"][name]["georef"]["dimid"]),
        fill_value=float(cntl["output_variables"][name]["fill_value"]),
    )
    v1.long_name = cntl["output_variables"][name]["long_name"]
    v1.standard_name = cntl["output_variables"][name]["standard_name"]
    v1.units = cntl["output_variables"][name]["out_units"]
    return v1


def write_timeseries_values(vals, nc_var):
    for ii in range(0, len(vals)):
        nc_var[ii, :] = vals[ii]


def write_timeseries_last_value(vals, nc_var):
    for ii in range(0, len(vals)):
        nc_var[ii] = vals[ii]


def write_ncf(output_path: Path, root_path: Path, varnames: list):
    # json_file = "/nhm/NHM_PRMS_CONUS_GF_1_1/variable_info_new.json"
    json_file = root_path / "variable_info_new.json"
    with open(json_file, "r") as read_file:
        cntl = json.load(read_file)

    # Read the PRMS output
    for var_name in varnames:
        dim_list = set()
        print(f"output path is {output_path}")
        fpath = output_path / f"{var_name}.csv"
        print(f"processing {fpath}")
        dim_list.add(cntl["output_variables"][var_name]["georef"]["dimid"])

        # csv_fn = cntl["output_variables"][var_name]["prms_out_file"]
        csv_fn = cntl["output_variables"][var_name]
        
        nts, nfeats, base_date, end_date, vals = read_output(fpath)
        conversion_factor = float(
            cntl["output_variables"][var_name]["conversion_factor"]
        )

        iis = len(vals)
        jjs = len(vals[0])

        for ii, jj in itertools.product(range(0, iis), range(0, jjs)):
            vals[ii, jj] = vals[ii, jj] * conversion_factor

        if "hruid" in dim_list:
            hru_lat_vals = read_feature_georef(root_path, "hru_lat")
            hru_lon_vals = read_feature_georef(root_path, "hru_lon")
            nhrus = len(hru_lat_vals)

        nsegments = -1
        if "segid" in dim_list:
            seg_lat_vals = read_feature_georef(root_path, "seg_lat")
            seg_lon_vals = read_feature_georef(root_path, "seg_lon")
            nsegments = len(seg_lat_vals)
        # write the ncf file
        # ofn = f"{str(output_path)}/{str(end_date)}_{var_name}.nc"
        ofn = output_path / f"{str(end_date)}_{var_name}.nc"

        print(f"writing netcdf file {ofn}")
        ncf = Dataset(ofn, "w", format="NETCDF4_CLASSIC")

        # Write dimensions block
        if nhrus > 0:
            hru_dim = ncf.createDimension("hruid", nhrus)
        if nsegments > 0:
            nsegments_dim = ncf.createDimension("segid", nsegments)
        time_dim = ncf.createDimension("time", None)

        # Put in the indexes for the dimensions
        base_date_obj = datetime.strptime(base_date, '%Y-%m-%d')
        time_idx = ncf.createVariable(
            "time",
            np.int32,
            ("time"),
        )
        time_idx.long_name = "time"
        time_idx.standard_name = "time"
        time_idx.cf_role = "timeseries_id"
        time_idx.units = f'days since {base_date} 00:00' + cntl["tz_code"]

        if nhrus > 0:
            hru_idx = ncf.createVariable(
                "hruid",
                np.int32,
                ("hruid"),
            )
            hru_idx.long_name = "local model hru id"

        if nsegments > 0:
            seg_idx = ncf.createVariable(
                "segid",
                np.int32,
                ("segid"),
            )
            seg_idx.long_name = "local model seg id"

        if nhrus > 0:
            hru_lat = write_variable_block(cntl, ncf, "hru_lat")
            hru_lon = write_variable_block(cntl, ncf, "hru_lon")

        if nsegments > 0:
            seg_lat = write_variable_block(cntl, ncf, "seg_lat")
            seg_lon = write_variable_block(cntl, ncf, "seg_lon")

        ncf.conventions = "CF-1.8"
        ncf.featureType = "timeSeries"
        ncf.history = (
            str(datetime.now())
            + ","
            + str(getpass.getuser())
            + ",prms_outputs2_ncf.py"
        )

        # Write data
        daily_steps = np.arange(nts)
        time_idx[:] = daily_steps
        if nhrus > 0:
            hru_idx[:] = np.arange(1, nhrus + 1, 1)
        if nsegments > 0:
            seg_idx[:] = np.arange(1, nsegments + 1, 1)

        if nhrus > 0:
            hru_lat[:] = hru_lat_vals
            hru_lon[:] = hru_lon_vals

        if nsegments > 0:
            seg_lat[:] = seg_lat_vals
            seg_lon[:] = seg_lon_vals

        ncf_var = write_timeseries_block(cntl, ncf, var_name)
        write_timeseries_values(vals, ncf_var )
        # write_timeseries_last_value(vals, ncf_var)
        ncf.close()

def valid_path(_type, value):
    if Path(value).exists():
        return value
    else:
        raise argparse.ArgumentTypeError(f"Path does not exist: {value}")
    
@app.default
def out2ncf(
        output_path: Annotated[
            str,
            Parameter(
                validator=valid_path,
                help="Directory containing output files *.csv",
                required=True
            )
        ], 
        root_path: Annotated[
            str,
            Parameter(
                validator=valid_path,
                help="Path to project root where variable_json_new.json and hru and seg lat/lon files reside",
                required=True
            )
        ],
    ):
    """
    Converts output files to NetCDF format.

    Args:
        output_path (str): Directory containing output files *.csv
        root_path (str): Path to project root where variable_json_new.json and hru and seg lat/lon files reside

    Returns:
        None
    """

    VARNAMES = [
        "dprst_stor_hru",
        "gwres_stor",
        "hru_impervstor",
        "hru_intcpstor",
        "pkwater_equiv",
        "soil_moist_tot",
        "seg_outflow",
        "seg_tave_water",
        "hru_impervstor",
        "hru_ppt",
        "hru_rain",
        "hru_snow",
        "potet",
        "hru_actet",
        "swrad",
        "tmaxf",
        "tminf",
        "tavgf",
        "dprst_evap_hru",
        "dprst_insroff_hru",
        "dprst_seep_hru",
        "dprst_vol_open_frac",
        "dprst_vol_open",
        "dprst_sroff_hru",
        "dprst_area_open",
        "ssres_flow",
        "slow_flow",
        "dunnian_flow",
        "hortonian_flow",
        "gwres_flow",
        "hru_sroffi",
        "hru_sroffp",
        "sroff",
        "hru_streamflow_out",
        "hru_lateral_flow",
        "pref_flow",
        "hru_outflow",
        "hru_intcpevap",
        "hru_impervevap",
        "net_ppt",
        "net_rain",
        "net_snow",
        "contrib_fraction",
        "albedo",
        "pk_depth",
        "pk_temp",
        "snowcov_area",
        "pk_ice",
        "pk_precip",
        "snow_evap",
        "snow_free",
        "snowmelt",
        "freeh2o",
        "soil_to_ssr",
        "soil_to_gw",
        "soil_rechr",
        "cap_waterin",
        "infil",
        "perv_actet",
        "pref_flow_stor",
        "recharge",
        "slow_stor",
        "soil_moist",
        "gwres_in",
        "prmx",
        "transp_on",
        "newsnow",
        "intcp_on",
        "seg_width",
        "seg_tave_upstream",
        "seg_tave_air",
        "seg_tave_gw",
        "seg_tave_sroff",
        "seg_tave_lat",
        "seg_shade",
        "seg_potet",
    ]
    # Convert strings to Path objects
    _output_path = Path(output_path)
    _root_path = Path(root_path)
    write_ncf(_output_path, _root_path, VARNAMES)

def main():
    try:
        app()
    except Exception as e:
        print(e)

if __name__ == "__main__":
    sys.exit(main())


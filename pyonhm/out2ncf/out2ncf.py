#!/usr/bin/env python3
"""
CSV to NetCDF Converter with Specific Variable Processing

This script converts specified tabular CSV files into CF-compliant NetCDF files.
Each CSV file should have a "Date" column followed by HRU or SEG IDs as headers.
Only variables listed in the VARNAMES list are processed.
Updated script based on original script developed by Steve Markstrom, USGS
"""

import argparse
from pathlib import Path
import pandas as pd
import json
import numpy as np
from netCDF4 import Dataset
from datetime import datetime
import logging
import sys
import os

# Configure logging at the very beginning
logging.basicConfig(
    level=logging.INFO,  # Set to INFO to capture INFO, WARNING, ERROR, and CRITICAL
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)  # Ensure logs are sent to stdout
    ]
)

logger = logging.getLogger(__name__)

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Convert specified CSV files to CF-compliant NetCDF files."
    )
    parser.add_argument(
        '--output-path',
        type=valid_path,
        required=True,
        help="Directory containing output *.csv files, including 'dprst_stor_hru.csv' and 'seg_outflow.csv'."
    )
    parser.add_argument(
        '--root-path',
        type=valid_path,
        required=True,
        help="Directory containing 'variable_info_new.json' and georeference CSV files."
    )
    return parser.parse_args()

def valid_path(path_str):
    path = Path(path_str)
    if not path.exists():
        raise argparse.ArgumentTypeError(f"Path does not exist: {path_str}")
    return path

def read_variable_info(json_path):
    try:
        with open(json_path, 'r') as f:
            variable_info = json.load(f)
        logger.info(f"Loaded variable info from {json_path}")
        return variable_info
    except Exception as e:
        logger.error(f"Failed to read variable info JSON: {e}")
        sys.exit(1)

def read_georef_csv(csv_path):
    """
    Read georeference CSV files without headers.

    Args:
        csv_path (Path): Path to the georeference CSV file.

    Returns:
        numpy.ndarray: Array of latitude or longitude values.
    """
    try:
        # Specify header=None to indicate no headers in the CSV files
        df = pd.read_csv(csv_path, header=None)
        if df.shape[1] != 1:
            raise ValueError(f"Expected one column in {csv_path}, got {df.shape[1]}")
        values = df.iloc[:,0].values
        logger.info(f"Read {len(values)} values from {csv_path}")
        return values
    except Exception as e:
        logger.error(f"Failed to read georef CSV {csv_path}: {e}")
        sys.exit(1)

def read_csv_data(csv_path):
    """
    Read data CSV files with a 'Date' column.

    Args:
        csv_path (Path): Path to the data CSV file.

    Returns:
        pandas.DataFrame: DataFrame containing the data with a 'time' column.
    """
    try:
        df = pd.read_csv(csv_path, parse_dates=['Date'], dayfirst=False)
        df.rename(columns={'Date': 'time'}, inplace=True)
        df['time'] = pd.to_datetime(df['time'], format='%m/%d/%Y')
        # logger.info(f"Read {len(df)} time steps from {csv_path}")
        return df
    except Exception as e:
        logger.error(f"Failed to read data CSV {csv_path}: {e}")
        sys.exit(1)

def extract_ids_from_csv(csv_path):
    """
    Extract IDs from the headers of a CSV file, excluding the 'Date' column.

    Args:
        csv_path (Path): Path to the CSV file.

    Returns:
        list: List of IDs as integers.
    """
    try:
        df_sample = pd.read_csv(csv_path, nrows=0)
        id_cols = [col for col in df_sample.columns if col != "Date"]
        ids = [int(col) for col in id_cols]
        # logger.info(f"Extracted IDs from {csv_path}: {ids}")
        return ids
    except Exception as e:
        logger.error(f"Failed to extract IDs from {csv_path}: {e}")
        sys.exit(1)

def create_netcdf_file(var_name, df, var_meta, georef, output_path):
    """
    Create a NetCDF file for a single variable.

    Args:
        var_name (str): Name of the variable.
        df (pandas.DataFrame): DataFrame containing the data.
        var_meta (dict): Metadata for the variable.
        georef (dict): Georeference data.
        output_path (Path): Directory to save the NetCDF file.

    Returns:
        None
    """
    # Extract time data
    time_data = df['time'].values
    nts = len(time_data)

    # Determine variable dimensions from var_meta['georef']['dimid']
    dimid = var_meta.get("georef", {}).get("dimid", "")
    if isinstance(dimid, str):
        dims = [dimid]  # Convert to list for consistency
    else:
        logger.info(f"No 'dimid' found for variable '{var_name}'. Skipping NetCDF creation.")
        return  # Exit the function early to skip NetCDF creation for this variable

    # Extract data (exclude 'time' column)
    data = df.drop(columns=['time']).values  # shape: (time, dim)

    # Apply conversion factor if present
    conversion_factor_str = var_meta.get("conversion_factor", '1.0')
    try:
        conversion_factor = float(conversion_factor_str)
    except ValueError:
        conversion_factor = 1.0
        logger.warning(f"Invalid conversion_factor '{conversion_factor_str}' for variable '{var_name}'. Using 1.0.")
    data = data.astype(float) * conversion_factor

    # Determine the number of features
    nfeat = data.shape[1]
    
    # Determine output NetCDF file name
    end_date = df['time'].iloc[-1].strftime('%Y%m%d')
    nc_filename = output_path / f"{end_date}_{var_name}.nc"

    logger.info(f"Creating NetCDF file: {nc_filename}")

    # Create NetCDF file
    with Dataset(nc_filename, "w", format="NETCDF4") as nc:
        # Define dimensions
        nc.createDimension("time", None)  # Unlimited
        if "hruid" in dims:
            nc.createDimension("hruid", len(georef["hruid_ids"]))
        if "segid" in dims:
            nc.createDimension("segid", len(georef["segid_ids"]))

        # Create time variable
        time_var = nc.createVariable("time", np.float64, ("time",))
        time_var.long_name = "time"
        time_var.standard_name = "time"
        time_var.units = f'days since {df["time"].iloc[0].strftime("%Y-%m-%d")} 00:00:00'
        time_var.calendar = "gregorian"

        # Assign time data as numeric values (e.g., days since base date)
        base_date = datetime.strptime(df["time"].iloc[0].strftime('%Y-%m-%d'), '%Y-%m-%d')
        time_numeric = np.array([(t - base_date).days for t in df["time"]])
        time_var[:] = time_numeric

        # Create spatial dimensions and variables
        if "hruid" in dims:
            hruid_var = nc.createVariable("hruid", np.int32, ("hruid",))
            hruid_var.long_name = "local model hru id"
            hruid_var[:] = georef["hruid_ids"]

            hru_lat = nc.createVariable("hru_lat", np.float64, ("hruid",))
            hru_lat.long_name = "HRU centroid latitude"
            hru_lat.units = "degrees_north"
            hru_lat[:] = georef["hru_lat"]

            hru_lon = nc.createVariable("hru_lon", np.float64, ("hruid",))
            hru_lon.long_name = "HRU centroid longitude"
            hru_lon.units = "degrees_east"
            hru_lon[:] = georef["hru_lon"]

        if "segid" in dims:
            segid_var = nc.createVariable("segid", np.int32, ("segid",))
            segid_var.long_name = "local model seg id"
            segid_var[:] = georef["segid_ids"]

            seg_lat = nc.createVariable("seg_lat", np.float64, ("segid",))
            seg_lat.long_name = "Segment centroid latitude"
            seg_lat.units = "degrees_north"
            seg_lat[:] = georef["seg_lat"]

            seg_lon = nc.createVariable("seg_lon", np.float64, ("segid",))
            seg_lon.long_name = "Segment centroid longitude"
            seg_lon.units = "degrees_east"
            seg_lon[:] = georef["seg_lon"]

        # Create the main data variable
        data_var = nc.createVariable(
            var_name,
            np.float32,
            ("time",) + tuple(dims),
            zlib=True,
            fill_value=float(var_meta.get("fill_value", '9.969209968386869e+36'))
        )

        data_var.long_name = var_meta.get("long_name", var_name)
        data_var.standard_name = var_meta.get("standard_name", "")
        data_var.units = var_meta.get("out_units", var_meta.get("in_units", ""))
        data_var.description = var_meta.get("description", "")

        # Assign data
        data_var[:, :] = data

        # Global attributes
        nc.Conventions = "CF-1.8"
        nc.featureType = "timeSeries"

        user = "pyonhm: pyonhm/out2ncf/out2ncf.py"
        nc.history = f"{datetime.now().isoformat()}"
        nc.source = user

def convert_variables_to_netcdf(output_path, root_path, variable_info, varnames, georef):
    """
    Convert specified variables to NetCDF files.

    Args:
        output_path (Path): Directory containing the CSV files.
        root_path (Path): Directory containing metadata and georef CSV files.
        variable_info (dict): Metadata information from JSON.
        varnames (list): List of variable names to process.
        georef (dict): Georeference data.

    Returns:
        None
    """
    for var_name in varnames:
        if var_name not in variable_info["output_variables"]:
            logger.warning(f"Variable '{var_name}' not found in variable_info_new.json. Skipping.")
            continue

        var_meta = variable_info["output_variables"][var_name]

        csv_file = output_path / f"{var_name}.csv"
        if not csv_file.exists():
            logger.warning(f"CSV file for variable '{var_name}' does not exist at {csv_file}. Skipping.")
            continue

        df = read_csv_data(csv_file)

        create_netcdf_file(var_name, df, var_meta, georef, output_path)

def main():
    args = parse_arguments()

    output_path = args.output_path
    root_path = args.root_path

    # Define VARNAMES list
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

    # Define required files for root_path and output_path
    required_files_root = [
        "variable_info_new.json",
        "hru_lat.csv",
        "hru_lon.csv",
        "seg_lat.csv",
        "seg_lon.csv"
    ]

    required_files_output = [
        "dprst_stor_hru.csv",
        "seg_outflow.csv"
    ]

    # Check for required files in root_path
    for file in required_files_root:
        file_path = root_path / file
        if not file_path.exists():
            logger.error(f"Required file '{file}' not found in root path '{root_path}'")
            sys.exit(1)

    # Check for required files in output_path
    for file in required_files_output:
        file_path = output_path / file
        if not file_path.exists():
            logger.error(f"Required file '{file}' not found in output path '{output_path}'")
            sys.exit(1)

    # Read variable info
    variable_info = read_variable_info(root_path / "variable_info_new.json")

    # Extract HRU IDs from 'dprst_stor_hru.csv'
    dprst_stor_hru_csv = output_path / "dprst_stor_hru.csv"
    hruid_ids = extract_ids_from_csv(dprst_stor_hru_csv)

    # Extract SEGID IDs from 'seg_outflow.csv'
    seg_outflow_csv = output_path / "seg_outflow.csv"
    segid_ids = extract_ids_from_csv(seg_outflow_csv)

    # Read georeference data from root_path
    hru_lat = read_georef_csv(root_path / "hru_lat.csv")
    hru_lon = read_georef_csv(root_path / "hru_lon.csv")
    seg_lat = read_georef_csv(root_path / "seg_lat.csv")
    seg_lon = read_georef_csv(root_path / "seg_lon.csv")

    # Verify that the number of IDs matches georef data
    if len(hruid_ids) != len(hru_lat) or len(hruid_ids) != len(hru_lon):
        logger.error("Mismatch between number of HRU IDs and georeference data.")
        sys.exit(1)
    if len(segid_ids) != len(seg_lat) or len(segid_ids) != len(seg_lon):
        logger.error("Mismatch between number of SEGID IDs and georeference data.")
        sys.exit(1)

    # Consolidate georef data
    georef_combined = {
        "hru_lat": hru_lat,
        "hru_lon": hru_lon,
        "seg_lat": seg_lat,
        "seg_lon": seg_lon,
        "hruid_ids": hruid_ids,
        "segid_ids": segid_ids,
    }

    # Convert variables to NetCDF
    convert_variables_to_netcdf(output_path, root_path, variable_info, VARNAMES, georef_combined)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        sys.exit(1)

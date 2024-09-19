import logging
import os
import pprint
import re
from typing import Tuple
import urllib3
import xmltodict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from pprint import pprint
from pprint import pformat
import pytz

# Configure logging
logger = logging.getLogger(__name__)


def adjust_date_str(date_str, days):
    """
    Adjusts a date by a certain number of days.

    Parameters:
    - date_str: The date in string format (%Y-%m-%d).
    - days: The number of days to adjust the date by. Can be negative.

    Returns:
    - The adjusted date as a string in %Y-%m-%d format.
    """
    date = datetime.strptime(date_str, "%Y-%m-%d")
    adjusted_date = date + timedelta(days=days)
    return adjusted_date.strftime("%Y-%m-%d")


def get_yesterday_mst():
    # Define MST timezone
    mst = pytz.timezone("America/Denver")

    # Get current time in UTC, then convert to MST
    now_utc = datetime.now(timezone.utc).replace(tzinfo=pytz.utc)
    now_mst = now_utc.astimezone(mst)

    return (now_mst - timedelta(days=1)).date()


# Function to get yesterday's date
def get_yesterday():
    return (datetime.now() - timedelta(days=1)).date()


# Function to add or subtract days from a given date
def adjust_date(date, days):
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).date()


def env_update_dates_for_restart_update(restart_date, env_vars):
    env_vars["RESTART_DATE"] = restart_date
    yesterday = get_yesterday_mst().strftime("%Y-%m-%d")
    # Directly setting START_DATE to restart_date + 1 day
    start_date = adjust_date_str(restart_date, 1)
    env_vars["START_DATE"] = start_date
    env_vars["SAVE_RESTART_DATE"] = adjust_date(yesterday, -59).strftime("%Y-%m-%d")

    # Setting END_DATE to SAVE_RESTART_DATE
    env_vars["END_DATE"] = env_vars["SAVE_RESTART_DATE"]

    # setting for updating new restart time
    env_vars["SAVE_RESTART_TIME"] = datetime.strptime(
        env_vars["END_DATE"], "%Y-%m-%d"
    ).strftime("%Y,%m,%d,00,00,00")

    # Save restart date in env vars
    env_vars["NEW_RESTART_DATE"] = restart_date


def env_update_dates_for_testing(restart_date, env_vars, num_days):
    yesterday = get_yesterday_mst().strftime("%Y-%m-%d")

    # Directly setting START_DATE to restart_date + 1 day
    start_date = adjust_date_str(restart_date, 1)
    env_vars["START_DATE"] = start_date

    # Setting END_DATE to START_DATE + num_days
    end_date = adjust_date_str(start_date, num_days)
    env_vars["END_DATE"] = end_date

    # Setting SAVE_RESTART_DATE if it's not set
    env_vars["SAVE_RESTART_DATE"] = end_date

    # Setting FRCST_END_DATE if it's not set
    if "FRCST_END_DATE" not in env_vars or not env_vars["FRCST_END_DATE"]:
        env_vars["FRCST_END_DATE"] = adjust_date(yesterday, 29).strftime("%Y-%m-%d")

    # Formatting FRCST_END_DATE for F_END_TIME
    env_vars["F_END_TIME"] = datetime.strptime(
        env_vars["FRCST_END_DATE"], "%Y-%m-%d"
    ).strftime("%Y,%m,%d,00,00,00")

    # setting for updating new restart time
    env_vars["SAVE_RESTART_TIME"] = datetime.strptime(
        env_vars["END_DATE"], "%Y-%m-%d"
    ).strftime("%Y,%m,%d,00,00,00")

    # Save restart date in env vars
    env_vars["NEW_RESTART_DATE"] = restart_date


def env_update_dates(restart_date, end_date, env_vars):
    env_vars["END_DATE"] = end_date
    env_vars["RESTART_DATE"] = restart_date
    env_vars["START_DATE"] = adjust_date(restart_date, 1).strftime("%Y-%m-%d")
    env_vars["SAVE_RESTART_DATE"] = adjust_date(end_date, -59).strftime("%Y-%m-%d")
    env_vars["FRCST_END_DATE"] = adjust_date(end_date, 29).strftime("%Y-%m-%d")

    # Formatting FRCST_END_DATE for F_END_TIME
    env_vars["F_END_TIME"] = datetime.strptime(
        env_vars["FRCST_END_DATE"], "%Y-%m-%d"
    ).strftime("%Y,%m,%d,00,00,00")

    # setting for updating new restart time
    env_vars["SAVE_RESTART_TIME"] = adjust_date(end_date, -59).strftime(
        "%Y,%m,%d,00,00,00"
    )
    # Save restart date in env vars
    env_vars["NEW_RESTART_DATE"] = restart_date

def env_update_forecast_dates(restart_date, env_vars):
    env_vars["FRCST_RESTART_DATE"] = restart_date
    start_date = adjust_date(restart_date, 1).strftime("%Y-%m-%d")
    env_vars["FRCST_START_DATE"] = start_date
    # Adding 27 to start days represents the 28 day forecast
    env_vars["FRCST_END_DATE"] = adjust_date(start_date, 27).strftime("%Y-%m-%d")

    # Formatting FRCST_END_DATE for FRCST_END_TIME
    env_vars["FRCST_END_TIME"] = datetime.strptime(
        env_vars["FRCST_END_DATE"], "%Y-%m-%d"
    ).strftime("%Y,%m,%d,00,00,00")

    # Formatting FRCST_END_DATE for FRCST_END_TIME
    env_vars["FRCST_START_TIME"] = datetime.strptime(
        env_vars["FRCST_START_DATE"], "%Y-%m-%d"
    ).strftime("%Y,%m,%d,00,00,00")

def get_ncf2cbh_opvars(env_vars: dict, mode: str, ensemble: int = 0):
    if mode == "ensemble":
        start_date = env_vars.get("FRCST_START_DATE")
        tvars = {
            "NCF2CBH_IDIR": env_vars.get("CFSV2_NCF_ENSEMBLE_IDIR") + start_date + "/",
            # "NCF2CBH_PREFIX": env_vars.get("OP_NCF_PREFIX"),
            "NCF2CBH_PREFIX": "converted_filled",
            "NCF2CBH_START_DATE": env_vars.get("START_DATE"),
            "NCF2CBH_ROOT_DIR": env_vars.get("PROJECT_ROOT"),
            "NCF2CBH_ENS_NUM": ensemble,
            "NCF2CBH_MODE": "ensemble"
        }
    elif mode == "median":
        start_date = env_vars.get("FRCST_START_DATE")
        tvars = {
            "NCF2CBH_IDIR": env_vars.get("CFSV2_NCF_ENSEMBLE_MED_IDIR") + start_date + "/",
            # "NCF2CBH_PREFIX": env_vars.get("CFSV2_NCF_MEDIAN_PREFIX"),
            "NCF2CBH_PREFIX": "converted_filled",
            "NCF2CBH_START_DATE": env_vars.get("FRCST_START_DATE"),
            "NCF2CBH_ROOT_DIR": env_vars.get("PROJECT_ROOT"),
            "NCF2CBH_ENS_NUM": 0,
            "NCF2CBH_MODE": "median"
        }

    elif mode == "op":
        tvars = {
            "NCF2CBH_IDIR": env_vars.get("OP_NCF_IDIR"),
            # "NCF2CBH_PREFIX": env_vars.get("OP_NCF_PREFIX"),
            "NCF2CBH_PREFIX": "converted_filled",
            "NCF2CBH_START_DATE": env_vars.get("START_DATE"),
            "NCF2CBH_ROOT_DIR": env_vars.get("PROJECT_ROOT"),
            "NCF2CBH_ENS_NUM": 0,
            "NCF2CBH_MODE": "op"

        }
    return tvars

def get_out2ncf_vars(env_vars: dict, mode: str, ensemble: int = 0):
    project_root = env_vars.get("PROJECT_ROOT")
    start_date_string = env_vars.get("FRCST_START_DATE")
    if mode == "ensemble":
        tvars = {
            "OUT_WORK_PATH": f"{project_root}/forecast/output/ensembles/{start_date_string}/ensemble_{int(ensemble)}",
            "OUT_ROOT_PATH": env_vars.get("PROJECT_ROOT")
        }
    elif mode == "median":
        start_date = env_vars.get("FRCST_START_DATE")
        tvars = {
            "OUT_WORK_PATH": f"{project_root}/forecast/output/ensemble_median/{start_date_string}",
            "OUT_ROOT_PATH": env_vars.get("PROJECT_ROOT")
        }
    elif mode == "op":
        tvars = {
            "OUT_WORK_PATH": env_vars.get("OP_DIR") + "/output",
            "OUT_ROOT_PATH": env_vars.get("PROJECT_ROOT")
        }
    return tvars

def get_forecast_median_prms_run_env(env_vars, restart_date):
   
    start_date_string = env_vars.get("FRCST_START_DATE")
    end_date_string = env_vars.get("FRCST_END_DATE")
    project_root = env_vars.get("PROJECT_ROOT")
    op_dir = env_vars.get("OP_DIR")
    frcst_dir = env_vars.get("FRCST_DIR")

    prms_env = {
        "OP_DIR": project_root,
        "FRCST_DIR": project_root,
        "PRMS_RESTART_DATE": restart_date,
        "PRMS_START_TIME": env_vars.get("FRCST_START_TIME"),
        "PRMS_END_TIME": env_vars.get("FRCST_END_TIME"),
        "PRMS_INIT_VARS_FROM_FILE": "1",
        "PRMS_VAR_INIT_FILE": f"{project_root}/forecast/restart/{restart_date}.restart",
        "PRMS_SAVE_VARS_TO_FILE": "0",
        "PRMS_CONTROL_FILE": env_vars.get("OP_PRMS_CONTROL_FILE"),
        "PRMS_RUN_TYPE": 1,
        "PRMS_INPUT_DIR": f"{project_root}/forecast/input/ensemble_median/{start_date_string}",
        "PRMS_OUTPUT_DIR": f"{project_root}/forecast/output/ensemble_median/{start_date_string}"
    }
    logger.debug("PRMS RUN ENV:\n%s", pformat(prms_env))
    
    return prms_env

def get_forecast_ensemble_prms_run_env(env_vars, restart_date, n):
   
    start_date_string = env_vars.get("FRCST_START_DATE")
    end_date_string = env_vars.get("FRCST_END_DATE")
    project_root = env_vars.get("PROJECT_ROOT")
    op_dir = env_vars.get("OP_DIR")
    frcst_dir = env_vars.get("FRCST_DIR")

    prms_env = {
        "OP_DIR": project_root,
        "FRCST_DIR": project_root,
        "PRMS_RESTART_DATE": restart_date,
        "PRMS_START_TIME": env_vars.get("FRCST_START_TIME"),
        "PRMS_END_TIME": env_vars.get("FRCST_END_TIME"),
        "PRMS_INIT_VARS_FROM_FILE": "1",
        "PRMS_VAR_INIT_FILE": f"{project_root}/forecast/restart/{restart_date}.restart",
        "PRMS_SAVE_VARS_TO_FILE": "0",
        "PRMS_CONTROL_FILE": env_vars.get("OP_PRMS_CONTROL_FILE"),
        "PRMS_RUN_TYPE": 1,
        "PRMS_INPUT_DIR": f"{project_root}/forecast/input/ensembles/{start_date_string}/ensemble_{int(n)}",
        "PRMS_OUTPUT_DIR": f"{project_root}/forecast/output/ensembles/{start_date_string}/ensemble_{int(n)}"
    }
    logger.debug("PRMS RUN ENV:\n%s", pformat(prms_env))
    
    return prms_env


def get_prms_run_env(env_vars, restart_date):
    start_date = datetime.strptime(env_vars.get("START_DATE"), "%Y-%m-%d")
    start_time = start_date.strftime("%Y,%m,%d,00,00,00")
    env_vars["START_TIME"] = start_time

    end_date = datetime.strptime(env_vars.get("END_DATE"), "%Y-%m-%d")
    end_time = end_date.strftime("%Y,%m,%d,00,00,00")
    end_date_string = env_vars.get("END_DATE")
    project_root = env_vars.get("PROJECT_ROOT")

    prms_env = {
        "OP_DIR": project_root,
        "FRCST_DIR": project_root,
        "PRMS_START_TIME": start_time,
        "PRMS_END_TIME": end_time,
        "PRMS_INIT_VARS_FROM_FILE": "1",
        "PRMS_RESTART_DATE": restart_date,
        "PRMS_VAR_INIT_FILE": f"{project_root}/daily/restart/{restart_date}.restart",
        "PRMS_SAVE_VARS_TO_FILE": "1",
        "PRMS_VAR_SAVE_FILE": f"{project_root}/forecast/restart/{end_date_string}.restart",
        "PRMS_CONTROL_FILE": env_vars.get("OP_PRMS_CONTROL_FILE"),
        "PRMS_RUN_TYPE": 0,
        "PRMS_INPUT_DIR": f"{project_root}/daily/input",
        "PRMS_OUTPUT_DIR": f"{project_root}/daily/output"
    }
    
    # Use pprint to format the dictionary for logging
    logger.debug("PRMS RUN ENV:\n%s", pformat(prms_env))
    
    return prms_env


def get_cfsv2_env(env_vars: dict, method: str):
    if method == "ensemble":
        mode = 2
    elif method == "median":
        mode = 1
    return {
        "MODEL_PARAM_FILE": env_vars.get("CFSV2_NCF_MPF"),
        "TARGET_FILE": env_vars.get("GM_TARGET_FILE"),
        "OUTPATH": env_vars.get("CFSV2_NCF_IDIR"),
        "WEIGHTS_FILE": env_vars.get("GM_WEIGHTS_FILE"),
        "METHOD": mode,
    }


def get_prms_restart_env(env_vars):
    # Convert START_DATE string to datetime object
    start_date = datetime.strptime(env_vars.get("START_DATE"), "%Y-%m-%d")
    # Format START_DATE as needed
    start_time = start_date.strftime("%Y,%m,%d,00,00,00")
    env_vars["START_TIME"] = start_time
    project_root = env_vars.get("PROJECT_ROOT")
    op_dir = env_vars.get("OP_DIR")
    frcst_dir = env_vars.get("FRCST_DIR")
    prms_restart_env = {
        "OP_DIR": project_root,
        "FRCST_DIR": project_root,
        "PRMS_START_TIME": env_vars.get("START_TIME"),
        "PRMS_END_TIME": env_vars.get("SAVE_RESTART_TIME"),
        "PRMS_INIT_VARS_FROM_FILE": 1,
        "PRMS_VAR_INIT_FILE": f"{project_root}/daily/restart/{env_vars.get('NEW_RESTART_DATE')}.restart",
        "PRMS_SAVE_VARS_TO_FILE": 1,
        "PRMS_VAR_SAVE_FILE": f"{project_root}/daily/restart/{env_vars.get('SAVE_RESTART_DATE')}.restart",
        "PRMS_CONTROL_FILE": env_vars.get("OP_PRMS_CONTROL_FILE"),
        "PRMS_RUN_TYPE": 0,
        "PRMS_INPUT_DIR": f"{project_root}/daily/input",
        "PRMS_OUTPUT_DIR": f"{project_root}/daily/output"
    }
    logger.debug("PRMS RUN ENV:\n%s", pformat(prms_restart_env))
    
    return prms_restart_env


def load_env_file(filename):
    env_dict = {}
    with open(filename) as file:
        for line in file:
            if line.startswith("#") or not line.strip():
                continue
            key, value = line.strip().split("=", 1)
            env_dict[key] = value
    return env_dict


def _getxml(url):
    http = urllib3.PoolManager()
    try:
        response = http.request("GET", url)
        data = xmltodict.parse(response.data)
        return data
    except Exception as e:  # Better error handling
        logger.exception("Error fetching or parsing XML from %s", url)
        return None


def gridmet_updated() -> bool:
    serverURL = "http://thredds.northwestknowledge.net:8080/thredds/ncss/grid"

    data_packets = [
        "agg_met_tmmn_1979_CurrentYear_CONUS.nc",
        "agg_met_tmmx_1979_CurrentYear_CONUS.nc",
        "agg_met_pr_1979_CurrentYear_CONUS.nc",
        "agg_met_rmin_1979_CurrentYear_CONUS.nc",
        "agg_met_rmax_1979_CurrentYear_CONUS.nc",
        "agg_met_vs_1979_CurrentYear_CONUS.nc",
    ]
    urlsuffix = "dataset.xml"

    tz = pytz.timezone("America/Denver")  # Replace with your timezone
    nowutc = datetime.now(pytz.utc)
    now = nowutc.astimezone(tz)
    yesterday = (now - timedelta(days=1)).date()

    status_list = []
    date_list = []

    for data in data_packets:
        masterURL = f"{serverURL}/{data}/{urlsuffix}"
        if xml_data := _getxml(masterURL):
            datadef = xml_data["gridDataset"]["TimeSpan"]["end"]
            gm_date = datetime.strptime(datadef[:10], "%Y-%m-%d").date()
            status_list.append(gm_date == yesterday)
            date_list.append(gm_date.strftime("%Y-%m-%d"))
        else:
            logger.error(f"Failed to fetch or parse data for {data}")
            status_list.append(False)
            date_list.append("")

    logger.info("Status of data availability (False = not from yesterday): %s", status_list)
    logger.info("Dates of the datasets: %s", date_list)
    return status_list, date_list



def is_next_day_present(date_folders: list[str], user_date: str) -> Tuple[bool, str]:
    """
    Determines if the next day after a user-specified date is present in a list of date folders.

    Args:
        date_folders (list[str]): List of date folders to check against.
        user_date (str): User-specified date in the format "%Y-%m-%d".

    Returns:
        Tuple[bool, str]: A tuple containing a boolean indicating presence of the next day and the date string if present, otherwise None.
    """

    # Parse the user-specified date
    user_date_dt = datetime.strptime(user_date, "%Y-%m-%d")

    # Calculate the next day
    next_day_dt = user_date_dt + timedelta(days=1)

    # Convert the next day back to string in YYYY-mm-dd format
    next_day_str = next_day_dt.strftime("%Y-%m-%d")

    # Check if the next day is in the list of date_folders
    is_present = next_day_str in date_folders

    # Return state and the date string if present, otherwise None
    return (is_present, next_day_str if is_present else None)

def check_consistency(status_list, date_list):
    # Ensure the date_list is not empty
    if not date_list:
        logger.warning("Date list is empty. Cannot proceed with consistency check.")
        return False, "", False

    all_dates_consistent = len(set(date_list)) == 1
    all_status_consistent = len(set(status_list)) == 1
    if all_status_consistent == 1 and all_dates_consistent:
        logger.info("Data is consistent with status: True and consistent dates.")
        return status_list[0], date_list[0]
    else:
        logger.warning(f"Data consistency check failed. Status: {status_list}, Dates: {date_list}")
        return False, ""

from cyclopts import App, Group, Parameter
import argparse
from io import BytesIO
import docker
import logging
import logging.config
import os
import sys
import subprocess
import yaml
from pyonhm import utils
from docker.errors import ContainerError, ImageNotFound, APIError
from datetime import datetime, timedelta
from pathlib import Path
import shlex
import time
from typing_extensions import Annotated
from typing import Any
from logging.handlers import RotatingFileHandler


utils.setup_logging()
logger = logging.getLogger(__name__)
logger.info("pyonhm application started")

app = App(
    default_parameter=Parameter(negative=()),
    )
g_build_load = Group.create_ordered(name="Admin Commands", help="Build images and load supporting data into volume")
g_operational = Group.create_ordered(name="Operational Commands", help="NHM daily operational model methods")
g_sub_seasonal = Group.create_ordered(name="Sub-seasonal Forecast Commands", help="NHM sub-seasonal forecasts model methods")
g_seasonal = Group.create_ordered(name="Seasonal Forecast Commands", help="NHM seasonal forecasts model methods")


def validate_forecast(type_, value: str):
    valid_forecasts = ["median", "ensemble"]
    if value not in valid_forecasts:
        raise  ValueError(f"Invalid --forecast-type: {value}. Expected one of {valid_forecasts}")

def validate_model(type_, value: str):
    valid_method = ["seasonal", "sub-seasonal"]
    if value not in valid_method:
        raise  ValueError(f"Invalid --method: {value}. Expected one of {valid_method}")

class DockerManager:
    def __init__(self):
        try:
            self.client = docker.from_env()
            self.volume_binding = {"nhm_nhm": {"bind": "/nhm", "mode": "rw"}}
        except docker.errors.DockerException as e:
            print(f"Failed to initialize Docker client: {e}")
            # Handle the failure as appropriate for your application
            # For example, you might want to raise the exception to halt execution
            # or set self.client to None and check before use in other methods.
            self.client = None
        except Exception as e:
            # Catch-all for any other exception, which might not be related to Docker directly
            print(f"An unexpected error occurred: {e}")
            self.client = None

    def build_image(self, context_path, tag, no_cache=False) -> bool:
        """
        Build docker image from context_path and tag. This is useful for debugging

        Args:
            context_path: path to docker image to build
            tag: tag to use for docker image ( ex : docker - v1 )
            no_cache: Don't use the cache when set to True
        """
        # Check if self.client is initialized
        if not self.client:
            logger.error("Docker client is not initialized. Cannot build image.")
            return False
        
        # Retrieve the GitHub token from an environment variable
        # github_token = os.getenv('GITHUB_TOKEN')
        # if not github_token:
        #     logger.error("GITHUB_TOKEN environment variable is not set. Cannot build image.")
        #     return False
        
        logger.info(f"Building Docker image: {tag} from {context_path}")
        try:
            response = self.client.images.build(
                path=context_path,
                tag=tag,
                rm=True,
                nocache=no_cache,
                # buildargs={'GITHUB_TOKEN': github_token}
            )
            # Iterate over the response to capture all output
            for chunk in response[1]:
                if 'stream' in chunk:
                    logger.info(chunk['stream'].strip())
                if 'errorDetail' in chunk:
                    logger.error(chunk['errorDetail']['message'].strip())
            return True
        except docker.errors.BuildError as build_error:
            logger.error(f"BuildError: {build_error}")
            if hasattr(build_error, 'build_log'):
                for chunk in build_error.build_log:
                    if 'stream' in chunk:
                        logger.info(chunk['stream'].strip())
                    if 'errorDetail' in chunk:
                        logger.error(f"ErrorDetail: {chunk['errorDetail']['message'].strip()}")
            return False
        except Exception as e:
            logger.exception("Failed to build Docker image.")
            return False

    def container_exists_and_running(self, container_name):
        """
        Check if a container exists and is running.

        This is useful for tests that need to know if a container exists and is running.

        Args:
                container_name: The name of the container

        Returns:
                A tuple of ( exists running )
        """
        try:
            container = self.client.containers.get(container_name)
            return True, container.status == "running"
        except docker.errors.NotFound:
            return False, False
    def manage_container(self, container_name, action):
        """Manage the lifecycle of a Docker container.

        This function checks the status of a specified container and performs the requested action, 
        either restarting it if it has exited or stopping and removing it. It logs the actions taken 
        and any errors encountered during the process.

        Args:
            container_name (str): The name of the container to manage.
            action (str): The action to perform on the container, either "restart" or "stop_remove".

        Returns:
            Container: The restarted container if the action is "restart".

        Raises:
            docker.errors.NotFound: If the specified container does not exist.
        """
        try:
            container = self.client.containers.get(container_name)
            if action == "restart" and container.status == "exited":
                logger.info(f"Restarting container '{container_name}'.")
                container.start()
                return container
            elif action == "stop_remove":
                logger.info(f"Stopping and removing container '{container_name}'.")
                container.stop()
                container.remove()
        except docker.errors.NotFound:
            logger.error(f"Container '{container_name}' not found.")


    def check_data_exists(self, image, container_name, volume, check_path) -> None:
        """Check if specific data exists in a Docker container.

        This function verifies the existence of data at a specified path within a Docker container. 
        It manages the container's state if it is found to be exited and runs a command to check for the data's
        presence.

        Args:
            image (str): The Docker image to use for running the container.
            container_name (str): The name of the container to check.
            volume (str): The volume to bind to the container.
            check_path (str): The path within the container to check for data.

        Returns:
            bool: True if the data exists at the specified path, False otherwise.

        Raises:
            Exception: If an error occurs while checking for data existence.
        """
        logger.info(f"Checking if data at {check_path} is downloaded...")
        exists, _running = self.container_exists_and_running(container_name)
        if exists:
            # Handle the exited container. You can either restart it or remove and recreate it.
            self.manage_container(container_name=container_name, action="stop_remove")

        command = ["sh", "-c", f"test -e {check_path} && echo 0 || echo 1"]
        container = self.client.containers.run(
            image=image,
            name=container_name,
            command=command,
            volumes=self.volume_binding,
            environment=["TERM=dumb"],
            remove=False,
            detach=True,
        )
        
        try:
            _result = container.wait()
            status_code = container.logs().decode("utf-8").strip()
            return status_code == "0"  # Returns True if data exists
        except Exception as e:
            logger.error(f"Error while checking data existence: {e}")
            return False


    def download_data(self, image, container_name, working_dir, download_path, download_commands) -> None:
        """Download data using a specified Docker container.

        This function checks if a container with the given name exists and manages its state if it does. 
        It then runs a new container to execute the provided download commands and logs the output of the operation.

        Args:
            image (str): The Docker image to use for running the container.
            container_name (str): The name of the container to run.
            working_dir (str): The working directory inside the container.
            download_path (str): The path where the data will be downloaded.
            download_commands (str): The shell commands to execute for downloading the data.

        Returns:
            bool: True if the download was successful, False otherwise.

        Raises:
            Exception: If there is an error while running the container or executing the download commands.
        """
        logger.info(f"Data needs to be downloaded at {download_path}")
        exists, _running = self.container_exists_and_running(container_name)
        if exists:
            # Handle the exited container. You can either restart it or remove and recreate it.
            self.manage_container(container_name=container_name, action="stop_remove")

        try:
            container = self.client.containers.run(
                image=image,
                name=container_name,
                command=f"sh -c '{download_commands}'",
                volumes=self.volume_binding,
                working_dir=working_dir,
                environment=["TERM=dumb"],
                remove=False,
                detach=True,
            )
            for log in container.logs(stream=True):
                logger.info(log.decode("utf-8").strip())

            container.reload()
            if container.status == "exited":
                exit_code = container.attrs['State']['ExitCode']
                if exit_code != 0:
                    logger.error(f"Container '{container_name}' exited with error code {exit_code}.")
                    return False
            return True
        except Exception as e:
            logger.exception(f"Failed to run container '{container_name}' for download.")
            return False



    def download_fabric_data(self, env_vars) -> None:
        """Download HRU data if it is not already present.

        This function checks for the existence of HRU data in a specified path and downloads it if it is not found. 
        It validates the necessary environment variables, removes any existing files, and constructs commands to download and extract the data.

        Args:
            env_vars (dict): A dictionary of environment variables required for the download process.

        Returns:
            None: This function does not return a value but logs the status of the download process.

        Raises:
            Exception: If there is an error while removing existing files or executing the download commands.
        """
        logger.info("Checking if HRU data exists...")

        if not self.check_data_exists(
            image="nhmusgs/base",
            container_name="base",
            volume="nhm_nhm",
            check_path="/nhm/gridmetetl/nhm_hru_data_gfv11",
        ):
            logger.info("HRU data not found. Proceeding with download.")

            # Validate required environment variables
            if 'HRU_SOURCE' not in env_vars or 'HRU_DATA_PKG' not in env_vars:
                logger.error("Missing required environment variables: HRU_SOURCE or HRU_DATA_PKG")
                return

            # Sanitize and validate inputs
            hru_source = shlex.quote(env_vars['HRU_SOURCE'])
            hru_data_pkg = shlex.quote(env_vars['HRU_DATA_PKG'])

            # Remove existing file if it exists
            existing_file_path = "/nhm/gridmetetl/nhm_hru_data_gfv11.zip"
            try:
                subprocess.run(["rm", "-f", existing_file_path], check=True)
                logger.info(f"Removed existing file: {existing_file_path}")
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to remove existing file: {e}")

            # Construct commands as a list of arguments
            download_commands = [
                f"wget --waitretry=3 --retry-connrefused --timeout=30 --tries=10 {hru_source}",
                f"unzip -o {hru_data_pkg} -d /nhm/gridmetetl",
                "chown -R nhm /nhm/gridmetetl",
                "chmod -R 766 /nhm/gridmetetl"
            ]

            # Log the commands for debugging purposes
            logger.debug("HRU download commands: %s", download_commands)

            # Pass the commands to the container to execute them
            self.download_data(
                image="nhmusgs/base",
                container_name="base",
                working_dir="/nhm",
                download_path="/nhm/gridmetetl/nhm_hru_data_gfv11",
                download_commands=" && ".join(download_commands),
            )

        else:
            logger.info("HRU data already exists. Skipping download.")


    def download_model_data(self, env_vars):
        """Download model data if it is not already present.

        This function checks for the existence of model data in a specified path and downloads it if it is not found.
        It validates the necessary environment variables, constructs commands to download and extract the data, and
        executes them.

        Args:
            env_vars (dict): A dictionary of environment variables required for the download process.

        Returns:
            None: This function does not return a value but logs the status of the download process.

        Raises:
            Exception: If there is an error while checking for existing data or executing the download commands.
        """
        logger.info("Checking if model data exists...")

        if not self.check_data_exists(
            image="nhmusgs/base",
            container_name="base",
            volume="nhm_nhm",
            check_path="/nhm/NHM_PRMS_CONUS_GF_1_1",
        ):
            logger.info("Model data not found. Proceeding with download.")

            # Validate required environment variables
            if 'PRMS_SOURCE' not in env_vars or 'PRMS_DATA_PKG' not in env_vars:
                logger.error("Missing required environment variables: PRMS_SOURCE or PRMS_DATA_PKG")
                return

            # Sanitize and validate inputs
            prms_source = shlex.quote(env_vars['PRMS_SOURCE'])
            prms_data_pkg = shlex.quote(env_vars['PRMS_DATA_PKG'])

            # Construct commands as a list of arguments
            prms_download_commands = [
                f"wget --waitretry=3 --retry-connrefused --timeout=30 --tries=10 {prms_source}",
                f"unzip {prms_data_pkg}",
                "chown -R nhm:nhm /nhm/NHM_PRMS_CONUS_GF_1_1",
                "chmod -R 766 /nhm/NHM_PRMS_CONUS_GF_1_1"
            ]

            # Log the commands for debugging purposes
            logger.debug("PRMS model download commands: %s", prms_download_commands)

            # Pass the commands to the container to execute them
            self.download_data(
                image="nhmusgs/base",
                container_name="base",
                working_dir="/nhm",
                download_path="/nhm/NHM_PRMS_CONUS_GF_1_1",
                download_commands=" && ".join(prms_download_commands),
            )

        else:
            logger.info("Model data already exists. Skipping download.")


    def download_model_test_data(self, env_vars):
        """Download model test data if it is not already present.

        This function checks for the existence of model test data in a specified path and downloads it if it is not
        found. It validates the necessary environment variables, constructs commands to download and extract the data,
        and executes them.

        Args:
            env_vars (dict): A dictionary of environment variables required for the download process.

        Returns:
            None: This function does not return a value but logs the status of the download process.

        Raises:
            Exception: If there is an error while checking for existing data or executing the download commands.
        """
        logger.info("Checking if model test data exists...")

        if not self.check_data_exists(
            image="nhmusgs/base",
            container_name="base",
            volume="nhm_nhm",
            check_path="/nhm/NHM_PRMS_UC_GF_1_1",
        ):
            logger.info("Model test data not found. Proceeding with download.")

            # Validate required environment variables
            if 'PRMS_TEST_SOURCE' not in env_vars or 'PRMS_TEST_DATA_PKG' not in env_vars:
                logger.error("Missing required environment variables: PRMS_TEST_SOURCE or PRMS_TEST_DATA_PKG")
                return

            # Sanitize and validate inputs
            prms_test_source = shlex.quote(env_vars['PRMS_TEST_SOURCE'])
            prms_test_data_pkg = shlex.quote(env_vars['PRMS_TEST_DATA_PKG'])

            # Construct commands as a list of arguments
            prms_test_download_commands = [
                f"wget --waitretry=3 --retry-connrefused --timeout=30 --tries=10 {prms_test_source}",
                f"unzip {prms_test_data_pkg}",
                "chown -R nhm:nhm /nhm/NHM_PRMS_UC_GF_1_1",
                "chmod -R 766 /nhm/NHM_PRMS_UC_GF_1_1"
            ]

            # Log the commands for debugging purposes
            logger.debug("PRMS model test download commands: %s", prms_test_download_commands)

            # Pass the commands to the container to execute them
            self.download_data(
                image="nhmusgs/base",
                container_name="base",
                working_dir="/nhm",
                download_path="/nhm/NHM_PRMS_UC_GF_1_1",
                download_commands=" && ".join(prms_test_download_commands),
            )

        else:
            logger.info("Model test data already exists. Skipping download.")

    def get_latest_restart_date(self, env_vars: dict, mode: str):
        """Finds and returns the date of the latest restart file in a specified directory within a Docker container.

        This function runs a Docker container to execute a shell command that lists all `.restart` files in a
        specific directory, sorts them, and extracts the date from the filename of the most recent file. It assumes
        that the filenames are structured such that the date can be isolated by removing the file extension.

        Args:
            env_vars (dict): A dictionary of environment variables where "PROJECT_ROOT" specifies the root directory
            of the project within the container's file system.
            mode (str): Either "op" or "forecast".

        Returns:
            str: The date of the latest restart file, extracted from its filename.

        Raises:
            ValueError: If the mode is not "op" or "forecast".
            FileNotFoundError: If no `.restart` files are found in the specified directory.
        """
        if mode not in ["op", "forecast"]:
            raise ValueError(f"Invalid mode '{mode}'. Mode must be 'op' or 'forecast'.")

        command = "bash -c 'ls -1 *.restart | sort | tail -1 | cut -f1 -d .'"
        project_root = env_vars.get("PROJECT_ROOT")
        
        # Check for any running containers associated with the image 'nhmusgs/base'
        try:
            running_containers = self.client.containers.list(all=True)
            for container in running_containers:
                # Adjust the check to handle the full tag format
                if any(tag.startswith("nhmusgs") for tag in container.image.tags):
                    logger.info(f"Stopping running container '{container.name}' associated with image 'nhmusgs/base'.")
                    container.stop()
                    # Wait until the container is fully stopped
                    container.reload()  # Reload the container's attributes to get the latest status
                    while container.status != "exited":
                        logger.info(f"Waiting for container '{container.name}' to stop...")
                        time.sleep(1)
                        container.reload()  # Check the status again
                    container.remove(force=True)
                    logger.info(f"Container '{container.name}' stopped and removed.")
        except Exception as e:
            logger.error(f"Error checking or stopping running containers: {e}")

        # Run the container to get the latest restart date
        try:
            container = self.client.containers.run(
                image="nhmusgs/base",
                command=command,
                volumes=self.volume_binding,
                working_dir=f"{project_root}/daily/restart" if mode == "op" else f"{project_root}/forecast/restart",
                environment={"TERM": "dumb"},
                detach=True,
                tty=True,
            )
            
            restart_date = container.logs().decode("utf-8").strip()
            container.remove()  # Clean up the container

            if not restart_date:
                raise FileNotFoundError("No .restart files found in the specified directory.")

            return restart_date

        except docker.errors.ContainerError as e:
            logger.error(f"Container error occurred: {e}")
        except docker.errors.ImageNotFound as e:
            logger.error(f"Docker image not found: {e}")
        except docker.errors.APIError as e:
            logger.error(f"Docker API error: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred while running the container: {e}")

        return None 


    def run_container(self, image, container_name, env_vars) -> bool:
        """Run a Docker container with the specified image and environment variables.

        This function checks if a container with the given name already exists and manages its state if it does. 
        It then attempts to run a new container using the specified image and logs the output of the container's execution.

        Args:
            image (str): The Docker image to use for running the container.
            container_name (str): The name of the container to run.
            env_vars (dict): A dictionary of environment variables to set in the container.

        Returns:
            bool: True if the container was successfully run, False otherwise.

        Raises:
            ContainerError: If there is an error related to the container.
            ImageNotFound: If the specified image does not exist.
            APIError: If there is an error with the Docker API.
        """
        exists, _running = self.container_exists_and_running(container_name)
        if exists:
            # Handle the exited container. You can either restart it or remove and recreate it.
            self.manage_container(container_name=container_name, action="stop_remove")
        try:
            logger.info(f"Running container '{container_name}' from image '{image}'...")
            container = self.client.containers.run(
                image=image,
                name=container_name,
                environment=env_vars,
                volumes=self.volume_binding,
                detach=True,
            )
            for log in container.logs(stream=True):
                logger.info(log.decode("utf-8").strip())
            container.reload()  # Reload the container's state
            if container.status == "exited":
                exit_code = container.attrs['State']['ExitCode']
                if exit_code != 0:
                    logger.error(f"Container '{container_name}' exited with error code {exit_code}.")
                    return False
            return True
        except (ContainerError, ImageNotFound, APIError) as e:
            logger.error(f"An error occurred: {e}")
            return False
        except Exception as e:
            logger.exception("An unexpected error occurred.")
            return False

    def run_container_old(self, image, container_name, env_vars):
        exists, _running = self.container_exists_and_running(container_name)
        if exists:
            # Handle the exited container. You can either restart it or remove and recreate it.
            self.manage_container(container_name=container_name, action="stop_remove")
        print(f"Running container '{container_name}' from image '{image}'...")
        container = self.client.containers.run(
            image=image,
            name=container_name,
            environment=env_vars,
            volumes=self.volume_binding,
            detach=True,
        )
        for log in container.logs(stream=True):
            print(log.decode("utf-8").strip())

    def build_images(self, no_cache: bool = False):
        """
        Build Docker images for various components of the application.
        """
        logger.info("Building Docker images...")
        components = [
            ("./pyonhm/base", "nhmusgs/base"),
            ("./pyonhm/gridmetetl", "nhmusgs/gridmetetl:0.30"),
            ("./pyonhm/ncf2cbh", "nhmusgs/ncf2cbh"),
            ("./pyonhm/prms", "nhmusgs/prms:5.2.1"),
            ("./pyonhm/out2ncf", "nhmusgs/out2ncf"),
            ("./pyonhm/cfsv2etl", "nhmusgs/cfsv2etl")
        ]

        for context_path, tag in components:
            success = self.build_image(context_path, tag, no_cache=no_cache)
            if not success:
                logger.error(f"Stopping build process due to failure in building {tag}.")
                return  # Stop execution if a build fails
        logger.info("Docker images built successfully.")



    def load_data(self, env_vars:dict):
        """
        Download necessary data using Docker containers.
        """
        logger.info("Downloading data...")
        self.download_fabric_data(env_vars=env_vars)
        self.download_model_data(env_vars=env_vars)
        self.download_model_test_data(env_vars=env_vars)

    def print_env_vars(self, env_vars):
        """
        Print selected environment variables.
        """
        print_keys = [
            "RESTART_DATE",
            "START_DATE",
            "END_DATE",
            "SAVE_RESTART_DATE",
        ]
        for key, value in env_vars.items():
            if key in print_keys:
                logger.info(f"{key}: {value}")

    def print_forecast_env_vars(self, env_vars: dict):
        """
        Print selected environment variables.
        """
        print_keys = [
            "FRCST_START_DATE",
            "FRCST_END_DATE",
            "FRCST_START_TIME",
            "FRCST_END_TIME"
        ]
        for key, value in env_vars.items():
            if key in print_keys:
                logger.info(f"{key}: {value}")
    def list_date_folders(self, path: Path):
        """
        Generates a list of date folders from the specified path by listing directories matching the date pattern.

        Args:
            path (Path): The path to search for date folders.

        Returns:
            list: A list of date folders extracted from the specified path.
        """

        # Bash command to list directories matching the date pattern
        command = f"bash -c 'find {path} -maxdepth 1 -type d | grep -E \"/[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$\"'"
        container = self.client.containers.run(
            image="nhmusgs/base",
            command=command,
            volumes=self.volume_binding,
            # environment={"TERM": "dumb"},
            detach=True,
            tty=True,
        )
        output = container.logs().decode("utf-8").strip()
        container.remove()  # Clean up the container

        # return [line.split('/')[-1] for line in output.split('\n')]
        return [line.strip().split('/')[-1] for line in output.split('\n')]

    def forecast_run(
            self,
            env_vars: dict,
            method: str = "median"
    ):
        """Execute forecast tasks based on the specified method.

        This function runs forecast tasks for either a median or ensemble method, checking for the latest restart date
        and preparing the necessary environment. It manages the execution of Docker containers to process climate data
        and logs the progress and results.

        Args:
            env_vars (dict): A dictionary of environment variables required for the forecast process.
            method (str): The method to use for the forecast, either "median" or "ensemble". Defaults to "median".

        Returns:
            None: This function does not return a value but logs the status of the forecast tasks.

        Raises:
            ValueError: If the specified method is not "median" or "ensemble".
        """
        logger.info(f"Running tasks for {method} forecast...")
        if method not in ["median", "ensemble"]:
            raise ValueError(f"Invalid method '{method}'. Mode must be 'median' or 'ensemble'.")
        
        median_path = Path(env_vars.get("CFSV2_NCF_IDIR")) / "ensemble_median"
        ensemble_path = Path(env_vars.get("CFSV2_NCF_IDIR")) / "ensembles"
        logger.info("Running forecast tasks...")
        
        # Get the most recent operational run restart date.
        forecast_restart_date = self.get_latest_restart_date(env_vars=env_vars, mode="forecast")
        logger.info(f"Forecast restart date is {forecast_restart_date}")
        
        utils.env_update_forecast_dates(restart_date=forecast_restart_date, env_vars=env_vars)
        self.print_forecast_env_vars(env_vars)

        # Get a list of dates representing the available processed climate drivers
        if method == "median":
            forecast_input_dates = self.list_date_folders(median_path)
        elif method == "ensemble":
            forecast_input_dates = self.list_date_folders(ensemble_path)

        state, forecast_run_date = utils.is_next_day_present(forecast_input_dates, forecast_restart_date)
        logger.info(f"{method} forecast ready: {state}, forecast start date: {forecast_run_date}")

        if method == 'median':
            med_vars = utils.get_ncf2cbh_opvars(env_vars=env_vars, mode=method, ensemble=0)
            success = self.run_container(
                image="nhmusgs/ncf2cbh", container_name="ncf2cbh", env_vars=med_vars
            )
            if not success:
                logger.error("Failed to run container 'ncf2cbh' for median ensemble. Exiting...")
                sys.exit(1)

            prms_env = utils.get_forecast_median_prms_run_env(env_vars=env_vars, restart_date=forecast_restart_date)
            success = self.run_container(
                image="nhmusgs/prms:5.2.1", container_name="prms", env_vars=prms_env
            )
            if not success:
                logger.error("Failed to run container 'prms'. Exiting...")
                sys.exit(1)

            out2ncf_vars = utils.get_out2ncf_vars(env_vars=env_vars, mode="median")
            success = self.run_container(
                image="nhmusgs/out2ncf",
                container_name="out2ncf",
                env_vars=out2ncf_vars,
            )
            if not success:
                logger.error("Failed to run container 'out2ncf'. Exiting...")
                sys.exit(1)

        elif method == "ensemble":
            for idx in range(48):  #  Loop through 48 ensembles
                logger.info(f"Running ensemble number: {idx}")
                med_vars = utils.get_ncf2cbh_opvars(env_vars=env_vars, mode=method, ensemble=idx)
                success = self.run_container(
                    image="nhmusgs/ncf2cbh", container_name="ncf2cbh", env_vars=med_vars
                )
                if not success:
                    logger.error(f"Failed to run container 'ncf2cbh' for ensemble: {idx}. Exiting...")
                    sys.exit(1)

                prms_env = utils.get_forecast_ensemble_prms_run_env(
                    env_vars=env_vars,
                    restart_date=forecast_restart_date,
                    n=idx)
                success = self.run_container(
                    image="nhmusgs/prms:5.2.1", container_name="prms", env_vars=prms_env
                )
                if not success:
                    logger.error(f"Failed to run container 'prms' for ensemble: {idx}. Exiting...")
                    sys.exit(1)

                out2ncf_vars = utils.get_out2ncf_vars(env_vars=env_vars, mode="ensemble", ensemble=idx)
                success = self.run_container(
                    image="nhmusgs/out2ncf",
                    container_name="out2ncf",
                    env_vars=out2ncf_vars,
                )
                if not success:
                    logger.error(f"Failed to run container 'out2ncf' for ensemble: {idx}. Exiting...")
                    sys.exit(1)


    def operational_run(
            self,
            env_vars: dict,
            test: bool = False,
            num_days: int = 4,
            override: bool = False  # Add override parameter
        ):
        """Execute operational tasks related to forecasting.

        Args:
            env_vars (dict): A dictionary of environment variables required for the operational run.
            test (bool): A flag indicating whether to run in test mode. Defaults to False.
            num_days (int): The number of days to consider for testing. Defaults to 4.
            override (bool): If True, override gm_status == False if dates are consistent.

        Returns:
            None: This function does not return a value but logs the status of the operational tasks.
        """
        logger.info("Running operational tasks...")
        
        try:
            restart_date = self.get_latest_restart_date(env_vars=env_vars, mode="op")
            logger.info(f"Operational restart date: {restart_date}")
        except Exception as e:
            logger.error(f"Failed to retrieve the latest restart date: {e}")
            return

        if test:
            try:
                utils.env_update_dates_for_testing(
                    restart_date=restart_date, env_vars=env_vars, num_days=num_days
                )
                logger.info(f"Environment dates updated for testing for {num_days} days.")
            except Exception as e:
                logger.error(f"Failed to update environment dates for testing: {e}")
                return
        else:
            try:
                status_list, date_list = utils.gridmet_updated()
                gm_status, end_date_str = utils.check_consistency(status_list, date_list)
                if gm_status == False and override:
                    logger.info("Override active: Using consistent date despite gm_status being False.")
                    gm_status = True  # Force gm_status to True to proceed
                elif gm_status == False:
                    logger.error("GridMet not yet updated - Try again later.")
                    return
                utils.env_update_dates(restart_date=restart_date, end_date=end_date_str, env_vars=env_vars)
                logger.info(f"GridMet updated relative to yesterday: {gm_status}")
            except Exception as e:
                logger.error(f"Failed to update environment dates: {e}")
                return

        self.print_env_vars(env_vars)
        
        try:
            self.op_containers(env_vars, restart_date)
            logger.info("Operational containers executed successfully.")
        except Exception as e:
            logger.error(f"Failed to run operational containers: {e}")


    def update_operational_restart(
                self,
                env_vars: dict,
        ):
        """Updates the operational restart for the Docker manager.

        Args:
            env_vars (dict): A dictionary containing environment variables.

        Returns:
            None
        """
        logger.info("Running restart update...")
        
        try:
            restart_date = self.get_latest_restart_date(env_vars=env_vars, mode="op")
            logger.info(f"The most recent restart date is {restart_date}")
        except Exception as e:
            logger.error(f"Failed to retrieve the latest restart date: {e}")
            return

        try:
            utils.env_update_dates_for_restart_update(restart_date=restart_date, env_vars=env_vars)
        except Exception as e:
            logger.error(f"Failed to update environment dates for restart: {e}")
            return

        print_keys = [
            "START_DATE",
            "END_DATE",
            "RESTART_DATE",
            "SAVE_RESTART_DATE",
        ]
        for key, value in env_vars.items():
            if key in print_keys:
                logger.info(f"{key}: {value}")  # Use logger instead of print

        try:
            self.update_restart_containers(env_vars=env_vars, restart_date=restart_date)
        except Exception as e:
            logger.error(f"Failed to update restart containers: {e}")

    def op_containers(self, env_vars, restart_date=None):
        """Run operational containers for data processing and analysis.

        This function manages the execution of multiple Docker containers necessary for operational tasks. 
        It checks the success of each container run and logs any errors, exiting the program if a container fails to start.

        Args:
            env_vars (dict): A dictionary of environment variables required for the operational run.
            restart_date (str, optional): The restart date to be used in the operational environment. Defaults to None.

        Returns:
            None: This function does not return a value but logs the status of the operational tasks.

        Raises:
            SystemExit: If a container fails to run or an error occurs during container operations.
        """
        logger.info("Starting operational containers...")

        try:
            self.run_container_with_check(image="nhmusgs/gridmetetl:0.30", container_name="gridmetetl", env_vars=env_vars)

            ncf2cbh_vars = utils.get_ncf2cbh_opvars(env_vars=env_vars, mode="op")
            self.run_container_with_check(image="nhmusgs/ncf2cbh", container_name="ncf2cbh", env_vars=ncf2cbh_vars)

            prms_env = utils.get_prms_run_env(env_vars=env_vars, restart_date=restart_date)
            self.run_container_with_check(image="nhmusgs/prms:5.2.1", container_name="prms", env_vars=prms_env)

            out2ncf_vars = utils.get_out2ncf_vars(env_vars=env_vars, mode="op")
            self.run_container_with_check(image="nhmusgs/out2ncf", container_name="out2ncf", env_vars=out2ncf_vars)

            prms_restart_env = utils.get_prms_restart_env(env_vars=env_vars)
            self.run_container_with_check(image="nhmusgs/prms:5.2.1", container_name="prms", env_vars=prms_restart_env)

        except Exception as e:
            logger.error(f"An error occurred during container operations: {e}")
            sys.exit(1)

    def run_container_with_check(self, image, container_name, env_vars):
        # Check if the container is running
        try:
            container = self.client.containers.get(container_name)
            if container.status == 'running':
                logger.info(f"Stopping running container '{container_name}' before proceeding.")
                container.stop()
        except docker.errors.NotFound:
            logger.info(f"Container '{container_name}' not found. Proceeding to run it.")

        success = self.run_container(image=image, container_name=container_name, env_vars=env_vars)
        if not success:
            logger.error(f"Failed to run container '{container_name}'. Exiting...")
            sys.exit(1)
    def update_restart_containers(self, env_vars, restart_date=None):
        """Update restart file to current day.

        This convenience method runs containers to forward the most recent restart file to what would be required
        to run the operational model today.
        """
        
        # def run_container_with_check(image, container_name, env_vars):
        #     success = self.run_container(image=image, container_name=container_name, env_vars=env_vars)
        #     if not success:
        #         logger.error(f"Failed to run container '{container_name}'. Exiting...")
        #         sys.exit(1)

        logger.info("Updating restart containers...")

        try:
            self.run_container_with_check(image="nhmusgs/gridmetetl:0.30", container_name="gridmetetl", env_vars=env_vars)

            ncf2cbh_vars = utils.get_ncf2cbh_opvars(env_vars=env_vars, mode="op")
            self.run_container_with_check(image="nhmusgs/ncf2cbh", container_name="ncf2cbh", env_vars=ncf2cbh_vars)

            prms_restart_env = utils.get_prms_restart_env(env_vars=env_vars)
            self.run_container_with_check(image="nhmusgs/prms:5.2.1", container_name="prms", env_vars=prms_restart_env)

            out2ncf_vars = utils.get_out2ncf_vars(env_vars=env_vars, mode="op")
            self.run_container_with_check(image="nhmusgs/out2ncf", container_name="out2ncf", env_vars=out2ncf_vars)

        except Exception as e:
            logger.error(f"An error occurred during the update of restart containers: {e}")
            sys.exit(1)

    def fetch_output(self, env_vars):
        """Fetch output files from a Docker container and manage the container lifecycle.

        This function initializes a Docker client, checks for an existing container, removes it if found, builds a new
        Docker image if necessary, and copies specified directories from the container to the host filesystem.

        Args:
            env_vars (dict): A dictionary containing environment variables, including paths for output and forecast
            directories.

        Returns:
            None: This function does not return a value but logs the status of the output fetching process.

        Raises:
            Exception: If there is an error while building the Docker image, copying directories, or managing
            containers.
        """
        client = docker.from_env()
        output_dir = env_vars.get("OUTPUT_DIR")
        frcst_dir = env_vars.get("FRCST_OUTPUT_DIR")
        project_root = env_vars.get("PROJECT_ROOT")
        logger.info(f'Output files will show up in the "{output_dir}" directory.')

        try:
            # Attempt to remove existing container if it exists
            existing_container = client.containers.get("volume_mounter")
            existing_container.remove(force=True)
            logger.info("Existing container 'volume_mounter' found and removed.")
        except docker.errors.NotFound:
            logger.info("No existing container 'volume_mounter' to remove.")

        # Check if the Docker image already exists
        try:
            client.images.get("nhmusgs/volume-mounter")
            logger.info("Docker image 'nhmusgs/volume-mounter' already exists.")
        except docker.errors.ImageNotFound:
            # Build a minimal Docker image (if not already exists)
            try:
                dockerfile = "FROM alpine\nCMD\n"
                client.images.build(
                    fileobj=BytesIO(dockerfile.encode("utf-8")),
                    tag="nhmusgs/volume-mounter",
                )
                logger.info("Docker image 'nhmusgs/volume-mounter' built successfully.")
            except docker.errors.BuildError as build_error:
                logger.error(f"Error building Docker image: {build_error}")
                return

        # Create a container with a volume attached
        container = client.containers.create(
            name="volume_mounter",
            image="nhmusgs/volume-mounter",
            volumes={"nhm_nhm": {"bind": "/nhm", "mode": "rw"}},
        )

        # Define the paths to copy
        paths_to_copy = [
            (f"{project_root}/daily/output", output_dir),
            (f"{project_root}/daily/input", output_dir),
            (f"{project_root}/daily/restart", output_dir),
            (f"{project_root}/forecast/input", frcst_dir),
            (f"{project_root}/forecast/output", frcst_dir),
            (f"{project_root}/forecast/restart", frcst_dir),
        ]

        try:
            for src_path, dest_dir in paths_to_copy:
                # Ensure the destination directory exists
                subprocess.run(["mkdir", "-p", dest_dir], check=True)
                # Copy each directory from the container to the host
                subprocess.run(
                    ["docker", "cp", f"volume_mounter:{src_path}", dest_dir], check=True
                )
            logger.info("Directories copied successfully.")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error copying directories: {e}")
        finally:
            # Cleanup
            try:
                container.remove()
                logger.info("Container 'volume_mounter' removed successfully.")
            except docker.errors.NotFound:
                logger.info("Container already removed or not found.")

    def ensure_volume_mounter_image(self):
        """
        Ensures that the 'volume_mounter' Docker image exists.
        If it doesn't, this method builds a minimal image.
        """
        try:
            self.client.images.get("nhmusgs/volume-mounter")
            logger.info("Docker image 'nhmusgs/volume-mounter' already exists.")
        except docker.errors.ImageNotFound:
            # Build a minimal Docker image
            try:
                dockerfile = "FROM alpine\nCMD [\"/bin/sh\"]"
                self.client.images.build(
                    fileobj=BytesIO(dockerfile.encode("utf-8")),
                    tag="nhmusgs/volume-mounter",
                )
                logger.info("Docker image 'nhmusgs/volume-mounter' built successfully.")
            except docker.errors.BuildError as build_error:
                logger.error(f"Error building Docker image: {build_error}")

    def list_available_forecasts(self, env_vars: dict, forecast_type: str, model: str):
        """
        Lists available forecasts based on the specified method and forecast type.

        Args:
            env_vars (dict): Environment variables loaded from the env_file.
            forecast_type (str): 'ensemble' or 'median'.
            model (str): 'sub-seasonal' or 'seasonal'.

        Returns:
            None
        """
        project_root = env_vars.get("PROJECT_ROOT")

        if forecast_type == "ensemble":
            forecast_input_dir = f"{project_root}/forecast/input/ensembles"
        elif forecast_type == "median":
            forecast_input_dir = f"{project_root}/forecast/input/ensemble_median"
        else:
            logger.error(f"Invalid method '{forecast_type}'. Must be 'ensemble' or 'median'.")
            return

        # Ensure the volume_mounter image exists
        self.ensure_volume_mounter_image()

        # Attempt to remove existing container if it exists
        try:
            existing_container = self.client.containers.get("volume_mounter")
            existing_container.remove(force=True)
            logger.info("Existing container 'volume_mounter' found and removed.")
        except docker.errors.NotFound:
            logger.info("No existing container 'volume_mounter' to remove.")

        # Create a container with the volume attached
        container = self.client.containers.create(
            name="volume_mounter",
            image="nhmusgs/volume-mounter",
            volumes={"nhm_nhm": {"bind": "/nhm", "mode": "rw"}},
            tty=True,  # Allocate a pseudo-TTY for the container
        )

        # Command to list directories
        command = f"ls -1 {forecast_input_dir}"

        try:
            # Start the container and execute the command
            container.start()
            exec_log = container.exec_run(cmd=command, stdout=True, stderr=True)
            output = exec_log.output.decode('utf-8').strip()

            if output:
                logger.info(f"Available forecasts in '{forecast_input_dir}':\n{output}")
                print(f"Available forecasts in '{forecast_input_dir}':\n{output}")
            else:
                logger.info(f"No forecasts found in '{forecast_input_dir}'.")
                print(f"No forecasts found in '{forecast_input_dir}'.")
        except Exception as e:
            logger.error(f"Error listing available forecasts: {e}")
        finally:
            # Clean up
            container.remove(force=True)
            logger.info("Container 'volume_mounter' removed after listing forecasts.")

    def update_cfsv2(self, env_vars: dict, method: str) -> None:
        """Update the CFSv2 environment by running a Docker container.

        This function retrieves the necessary environment variables for the CFSv2 processing based on the specified method 
        and runs a Docker container to process the data. It logs any errors encountered during the retrieval of environment 
        variables or the execution of the container.

        Args:
            env_vars (dict): A dictionary of environment variables required for the CFSv2 processing.
            method (str): The method to use for the CFSv2 update.

        Returns:
            None: This function does not return a value but logs the status of the update process.

        Raises:
            Exception: If there is an error while retrieving the CFSv2 environment variables or running the container.
        """
        try:
            cfsv2_env = utils.get_cfsv2_env(env_vars=env_vars, method=method)
        except Exception as e:
            logger.error(f"Failed to retrieve CFSv2 environment variables: {e}")
            return

        success = self.run_container(
            image="nhmusgs/cfsv2etl",
            container_name="cfsv2_env",
            env_vars=cfsv2_env,
        )
        
        if not success:
            logger.error("Failed to run the CFSv2 container.")

@app.command(group=g_operational)
def run_operational(
    *,
    env_file: str, 
    test: bool = False, 
    num_days: int = 4, 
    override: bool = False
) -> None:
    """Runs the operational simulation using the DockerManager.

    Args:
        env_file: The path to the environment file.
        test: If True, runs the simulation in test mode. Defaults to False.
        num_days: If test is True, then the number of days to run the simulation. Defaults to 4.
        override: If True, override gm_status == False when dates are consistent. Defaults to False.

    Returns:
        None
    """
    docker_manager = DockerManager()

    try:
        dict_env_vars = utils.load_env_file(env_file)
        logger.info(f"Environment variables loaded from '{env_file}'.")
    except Exception as e:
        logger.error(f"Failed to load environment file '{env_file}': {e}")
        return

    if docker_manager.client is not None:
        logger.info("Docker client initialized successfully.")
    else:
        logger.error("Failed to initialize Docker client.")
        return

    # Log to inform the user about how num_days is used
    if test:
        logger.info(f"Running in test mode for {num_days} days.")
    else:
        logger.info("Running in normal mode. --num_days will be ignored.")

    try:
        docker_manager.operational_run(env_vars=dict_env_vars, test=test, num_days=num_days, override=override)
    except Exception as e:
        logger.error(f"An error occurred while running the operational simulation: {e}")



@app.command(group=g_sub_seasonal)
def run_sub_seasonal(*, env_file: str, method: str) -> None:
    """
    Runs the sub-seasonal operational simulation using the DockerManager.

    Args:
        env_file (str): The path to the environment file.
        method (str): One of ["median"]["ensemble"]  

    Returns:
        None
    """
    docker_manager = DockerManager()
    dict_env_vars = utils.load_env_file(env_file)
    if docker_manager.client is not None:
        print("Docker client initialized successfully.")
    else:
        print("Failed to initialize Docker client.")
    docker_manager.forecast_run(env_vars=dict_env_vars, method=method)
    print("TODO")

@app.command(group=g_sub_seasonal)
def run_list_available_forecasts(
        env_file:str,
        forecast_type: 
        Annotated[
            str,
            Parameter(
                validator=validate_forecast
            )
        ], 
        model:
        Annotated[ 
            str,
            Parameter(
                validator=validate_model
            )
        ]
):
    """
    Lists available forecasts based on the specified forecast type and method.

    Args:
        env_file (str): Path to the environment file.
        forecast_type (str): 'median' or 'ensemble'.
        method (str): 'ensemble' or 'median'.

    Returns:
        None
    """
    docker_manager = DockerManager()
    dict_env_vars = utils.load_env_file(env_file)

    if docker_manager.client is not None:
        logger.info("Docker client initialized successfully.")
    else:
        logger.error("Failed to initialize Docker client.")
        return

    try:
        docker_manager.list_available_forecasts(
            env_vars=dict_env_vars,
            forecast_type=forecast_type,
            model=model,
        )
    except Exception as e:
        logger.error(f"An error occurred while listing available forecasts: {e}")

@app.command(group=g_sub_seasonal)
def run_update_cfsv2_data(*, env_file: str, method: str):
    """
    Runs the update of CFSv2 data using the specified method , either 'ensemble' or 'median'.

    Args:
        env_file (str): Path to the environment file.
        method (str): The method to use for updating data, either 'ensemble' or 'median'.

    Returns:
        None
    """
    docker_manager = DockerManager()
    dict_env_vars = utils.load_env_file(env_file)
    if docker_manager.client is not None:
        print("Docker client initialized successfully.")
    else:
        print("Failed to initialize Docker client.")
    if method not in ["ensemble", "median"]:
        print(f"Error: '{method}' is not a valid method. Please use 'ensemble' or 'median'.")
        sys.exit(1)  # Exit with error code 1 to indicate failure
    
    docker_manager.update_cfsv2(env_vars=dict_env_vars, method=method)

@app.command(group=g_seasonal)
def run_seasonal(*, env_file: str, num_days: int=4, test:bool=False):
    """
    Runs the seasonal operational simulation using the DockerManager.

    Args:
        env_file: The path to the environment file.
        num_days: The number of days to run the simulation for. Defaults to 4.
        test: If True, runs the simulation in test mode. Defaults to False.

    Returns:
        None
    """
    docker_manager = DockerManager()
    dict_env_vars = utils.load_env_file(env_file)
    if docker_manager.client is not None:
        print("Docker client initialized successfully.")
    else:
        print("Failed to initialize Docker client.")
    
    
    print("TODO")

@app.command(group=g_build_load)
def build_images(*, no_cache: bool=False):
    """
    Builds Docker images using the DockerManager.

    Args:
        no_cache: If True, builds the images without using cache. Defaults to False.

    Returns:
        None
    """
    docker_manager = DockerManager()
    if docker_manager.client is not None:
        print("Docker client initialized successfully.")
    else:
        print("Failed to initialize Docker client.")
    
    docker_manager.build_images(no_cache=no_cache)

@app.command(group=g_build_load)
def update_operational_restart(*, env_file: str):
    """
    Updates the operational restart using the provided environment file.

    Args:
        env_file (str): Path to the environment file.

    Returns:
        None
    """
    docker_manager=DockerManager()
    dict_env_vars = utils.load_env_file(env_file)
    if docker_manager.client is not None:
        print("Docker client initialized successfully.")
    else:
        print("Failed to initialize Docker client.")
    docker_manager.update_operational_restart(env_vars=dict_env_vars)

@app.command(group=g_build_load)
def load_data(*, env_file: str):
    """
    Loads data using the DockerManager.

    Args:
        env_file: The path to the environment file.

    Returns:
        None
    """
    docker_manager = DockerManager()
    dict_env_vars = utils.load_env_file(env_file)
    if docker_manager.client is not None:
        print("Docker client initialized successfully.")
    else:
        print("Failed to initialize Docker client.")
    docker_manager.load_data(env_vars=dict_env_vars)

@app.command(group=g_operational)
def fetch_op_results(*, env_file: str):
    """
    Fetches operational results using the DockerManager.

    Args:
        env_file: The path to the environment file.

    Returns:
        None
    """
    docker_manager = DockerManager()
    dict_env_vars = utils.load_env_file(env_file)
    if docker_manager.client is not None:
        print("Docker client initialized successfully.")
    else:
        print("Failed to initialize Docker client.")
    docker_manager.fetch_output(env_vars=dict_env_vars)

def main():
    try:
        app()
    except Exception as e:
        print(e)

if __name__ == "__main__":
    main()
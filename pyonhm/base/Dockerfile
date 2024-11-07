# # NHM Base Image
#
# This is the base image used to build the NHM pipeline.

FROM condaforge/miniforge3:latest

LABEL maintainer_1="rmcd@usgs.gov" \
      maintainer_2="ahalper@usgs.gov"

# ## Additional Packages
#
# Several additional packages are installed on the base image to
# provide features necessary for building and running the NHM
# pipeline:
#
#    * Secure networking
#        - [ca-certificates](https://packages.debian.org/bullseye/ca-certificates)
#    * APT package management system
#        - [dialog](https://packages.debian.org/bullseye/dialog)
#    * Pipeline debugging
#        - [file](https://packages.debian.org/bullseye/file)
#    * PRMS build prerequisites
#        - [gcc](https://packages.debian.org/bullseye/gcc)
#        - [gfortran](https://packages.debian.org/bullseye/gfortran)
#        - [libhdf5-mpich-dev](https://packages.debian.org/bullseye/libhdf5-mpich-dev)
#        - [libnetcdf-dev](https://packages.debian.org/bullseye/libnetcdf-dev)
#        - [libnetcdff-dev](https://packages.debian.org/bullseye/libnetcdff-dev)
#        - [make](https://packages.debian.org/bullseye/make)
#    * Docker shared volume support
#        - [procps](https://packages.debian.org/bullseye/procps)
#    * Git source download unarchiving
#        - [unzip](https://packages.debian.org/bullseye/unzip)
#    * Vim for development editing
#        - [vim](https://packages.debian.org/bullseye/vim)
#

# Create nhm group and user first
RUN groupadd -g 1000 nhm && useradd -u 1000 -g nhm -ms /bin/bash nhm

# Ensure the NHM_SOURCE_DIR exists and has correct permissions
RUN mkdir -p /usr/local/src && chown -R nhm:nhm /usr/local/src

# Prevent halting due to tzdata, interactive package config. See
# https://serverfault.com/questions/84521/automate-dpkg-reconfigure-tzdata
RUN ln -fs /usr/share/zoneinfo/UTC /etc/localtime

# Additional Packages and Configuration
RUN apt-get update --fix-missing && \
    apt-get -q -y install \
        apt-utils \
        ca-certificates \
        dialog \
        file \
        gcc \
        gfortran \
        libhdf5-mpich-dev \
        libnetcdf-dev \
        libnetcdff-dev \
        make \
        procps \
        unzip \
        vim && \
    apt-get autoclean && apt-get purge

# Copy and update certificates
COPY DOIRootCA2.cer /usr/local/share/ca-certificates/DOIRootCA2.crt
RUN update-ca-certificates

# Set environment variables for SSL certificates
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV CURL_CA_BUNDLE=${SSL_CERT_FILE}
ENV PIP_CERT=${SSL_CERT_FILE}
ENV GIT_SSL_CAINFO=${SSL_CERT_FILE}
ENV REQUESTS_CA_BUNDLE=${SSL_CERT_FILE}

# Verify environment variables
RUN echo "SSL_CERT_FILE=${SSL_CERT_FILE}" && \
    echo "CURL_CA_BUNDLE=${CURL_CA_BUNDLE}" && \
    echo "PIP_CERT=${PIP_CERT}" && \
    echo "GIT_SSL_CAINFO=${GIT_SSL_CAINFO}" && \
    echo "REQUESTS_CA_BUNDLE=${REQUESTS_CA_BUNDLE}"

# Conda and Python Setup
RUN mamba update -n base mamba -y && \
    mamba install -n base -c conda-forge -y \
        python=3.11 \
        pip \
        gdptools=0.2.10 \
        cyclopts \
        dask \
        bottleneck \
        geopandas \
        nco \
        netcdf4 \
        pandas \
        requests \
        xarray \
        xmltodict \
        pint-xarray && \
    mamba clean -a

# # ## Source Code Location
# #
# # The NHM source code location can be configured by setting the base
# # image's `NHM_SOURCE_DIR` environment variable.
ENV NHM_SOURCE_DIR=/usr/local/src

# Install gridmet-etl into conda base environment for use with climage ETL processes.
RUN pip install -vvv --trusted-host pypi.org --trusted-host files.pythonhosted.org git+https://github.com/rmcd-mscb/gridmet-etl.git

# Define source directory and user environment
ENV NHM_SOURCE_DIR=/usr/local/src
ENV USER=nhm
ENV HOMEDIR=/home/$USER

# Set default user to nhm
USER nhm

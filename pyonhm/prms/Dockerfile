# # NHM PRMS Image
#
# This image contains PRMS.
FROM nhmusgs/base

LABEL maintainer="rmcd@usgs.gov"

# ## PRMS Version Numberdock
#
# The PRMS version number can be defined by setting the
# `VERSION_TAG_PRMS` argument.
ARG VERSION_TAG_PRMS=5.2.1

# Ensure the NHM_SOURCE_DIR exists and has correct permissions
RUN mkdir -p $NHM_SOURCE_DIR && chown -R nhm:nhm $NHM_SOURCE_DIR

# The PRMS source code is hosted on GitHub (as opposed to CHS GitLab).
RUN wget -q -P $NHM_SOURCE_DIR \
    https://github.com/nhm-usgs/prms/archive/refs/heads/$VERSION_TAG_PRMS.zip

# PRMS is builit with the "-fallow-argument-mismatch" flag to allow
# compilation of pre-GFortran-10.x code.
RUN cd $NHM_SOURCE_DIR && unzip $VERSION_TAG_PRMS.zip && rm $VERSION_TAG_PRMS.zip && \
    mv prms-$VERSION_TAG_PRMS prms && mkdir bin && cd prms && \
    make CFLAGS='$(OPTLEVEL) -D$(ARC) -D_UF -Wall' \
         FFLAGS='$(OPTLEVEL) -w -fno-second-underscore -Wno-argument-mismatch -I/opt/conda/include'

# ## PRMS Installation Location
#
# The PRMS program installs in `/usr/local/bin`.
COPY --chown=nhm prms /usr/local/bin
RUN chmod 744 /usr/local/bin/prms

# Copy the Python entrypoint script
COPY --chown=nhm run_prms.py /usr/local/bin/run_prms.py
RUN chmod +x /usr/local/bin/run_prms.py

# ## PRMS User Account
#
# The PRMS user account is defined in the [base image
# Dockerfile](https://code.chs.usgs.gov/wma/nhm/docker-images/-/blob/main/base/Dockerfile).
USER $USER
WORKDIR /home/$USER

# Set the entrypoint to use Python from the Conda environment
ENTRYPOINT ["/opt/conda/bin/python", "/usr/local/bin/run_prms.py"]

# ENTRYPOINT ["/bin/bash", "-c", "/usr/local/bin/prms"]

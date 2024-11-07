# # NHM gridmetetl Image
#
# This image contains the gridmetetl program.
FROM nhmusgs/base

LABEL maintainer="rmcd@usgs.gov"

# ## gridmetetl Installation Location
#
# The gridmetetl program installs in `/usr/local/bin`.
COPY --chown=nhm run_cfsv2etl /usr/local/bin
RUN chmod 744 /usr/local/bin/run_cfsv2etl

# # ## gridmetetl User Account
# #
# # The gridmetetl user account is defined in the [base image
# # Dockerfile](https://code.chs.usgs.gov/wma/nhm/docker-images/-/blob/main/base/Dockerfile).
# USER $USER
# WORKDIR /home/$USER

ENTRYPOINT ["/bin/bash", "-c", "run_cfsv2etl"]

# # NHM gridmetetl Image
#
# This image contains the out2ncf program.
FROM nhmusgs/base

LABEL maintainer="rmcd@usgs.gov"

# Copy python script into image
COPY --chown=nhm out2ncf.py /opt/conda/bin
RUN chmod 744 /opt/conda/bin/out2ncf.py
# ## out2ncf Installation Location
#
# The out2ncf program installs in `/usr/local/bin`.
COPY --chown=nhm out2ncf /usr/local/bin
RUN chmod 744 /usr/local/bin/out2ncf

# # ## out2ncf User Account
# #
# # The out2ncf user account is defined in the [base image
# # Dockerfile](https://code.chs.usgs.gov/wma/nhm/docker-images/-/blob/main/base/Dockerfile).
# USER $USER
# WORKDIR /home/$USER

ENTRYPOINT ["/bin/bash", "-c", "/usr/local/bin/out2ncf"]

# NHM ncf2cbh Image
#
# This image contains the ncf2cbh program.
FROM nhmusgs/base

LABEL maintainer="rmcd@usgs.gov"

# Copy python script into image
COPY --chown=nhm ncf2cbh_gfv11_embedded.py /opt/conda/bin
RUN chmod 744 /opt/conda/bin/ncf2cbh_gfv11_embedded.py

# ncf2cbh Installation Location
#
# The ncf2cbh program installs in `/usr/local/bin`.
COPY --chown=nhm ncf2cbh /usr/local/bin
RUN chmod 755 /usr/local/bin/ncf2cbh  # Ensure executable permissions

# # ncf2cbh User Account
# #
# # The ncf2cbh user account is defined in the [base image
# # Dockerfile](https://code.chs.usgs.gov/wma/nhm/docker-images/-/blob/main/base/Dockerfile).
# USER $USER
# WORKDIR /home/$USER

# Set ENTRYPOINT to directly execute the script
ENTRYPOINT ["/usr/local/bin/ncf2cbh"]

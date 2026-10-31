# DEDALUS development environment: ROS 2 Jazzy + CARLA 0.9.16 Python client.
#
# Environment only. This image never contains project code: the colcon
# workspace is bind-mounted at /ws at run time (see compose.yml). Do not add
# COPY/ADD lines that pull in source.
FROM ros:jazzy-ros-base

# ROS packages and tools the DEDALUS nodes need (declared explicitly, no rosdep
# at build time because the package.xml files are not part of this image).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-jazzy-ackermann-msgs \
    ros-jazzy-tf2-ros \
    ros-jazzy-robot-localization \
    ros-jazzy-foxglove-bridge \
    ros-jazzy-rosbag2 \
    ros-jazzy-rosbag2-storage-mcap \
    ros-jazzy-image-transport-plugins \
    ros-jazzy-cv-bridge \
    python3-pip python3-numpy python3-opencv python3-matplotlib \
    git nano \
    && rm -rf /var/lib/apt/lists/*

# CARLA Python client, same version as the simulator image (Python 3.12 wheel).
RUN pip install --no-cache-dir --break-system-packages carla==0.9.16

# One middleware in the whole graph: Fast DDS (the ROS 2 Jazzy default).
ENV RMW_IMPLEMENTATION=rmw_fastrtps_cpp

# Non-root user "ubuntu" (UID 1000, already present in the Ubuntu 24.04 base).
# Files written to /ws and /bags then belong to the person on the host machine.
RUN id -u ubuntu >/dev/null 2>&1 || useradd -m -u 1000 -s /bin/bash ubuntu
RUN mkdir -p /ws/src /bags && chown -R ubuntu:ubuntu /ws /bags
RUN echo 'source /opt/ros/jazzy/setup.bash' >> /home/ubuntu/.bashrc && \
    echo '[ -f /ws/install/setup.bash ] && source /ws/install/setup.bash' >> /home/ubuntu/.bashrc && \
    echo 'alias cs="cd /ws && colcon build --symlink-install && source install/setup.bash"' >> /home/ubuntu/.bashrc && \
    chown ubuntu:ubuntu /home/ubuntu/.bashrc

USER ubuntu
WORKDIR /ws
CMD ["bash"]

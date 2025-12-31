FROM osrf/ros:humble-desktop-full

# Install Zsh, Git, and clean up apt cache to keep image small
RUN apt-get update && apt-get install -y \
    zsh \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Oh My Zsh (unattended mode)
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended

# Create a place for your ROS workspace later
WORKDIR /ros2_ws

# Set Zsh as the default entry shell
CMD ["zsh"]

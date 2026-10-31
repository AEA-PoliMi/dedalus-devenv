# DEDALUS development environment

Docker environment for the DEDALUS autonomous-driving stack: the CARLA 0.9.16
simulator plus a ROS 2 Jazzy container with every dependency the DEDALUS nodes
need. **This repository contains no DEDALUS project code; the only code is a
stand-alone CARLA smoke test under `smoke/`.** You bring your own colcon
workspace; it is bind-mounted into the container at run time and never copied
into the image (the smoke test is bind-mounted read-only at `/smoke`, too).

| Service | Image | Role |
|---|---|---|
| `carla` | `carlasim/carla:0.9.16` (official) | Simulator, headless, GPU, RPC on `localhost:2000` |
| `ros2` | `dedalus-devenv:jazzy` (built here) | ROS 2 Jazzy + `carla` Python client 0.9.16, Fast DDS, rosbag2/MCAP, foxglove_bridge, robot_localization, cv_bridge, OpenCV, NumPy, Matplotlib, colcon |

How the team uses it:

- **Hosts** are the 4-5 team PCs with an NVIDIA GPU. Each host runs one CARLA
  and the host owner's own `ros2` container.
- **Guests** are everyone else. A guest connects to a host over Tailscale +
  SSH and works *on the host*, in their own compose project, with their own
  workspace folder. Nothing runs on the guest laptop except VS Code and Foxglove.

## Prerequisites

### Host (PC with NVIDIA GPU)

- Linux (tested on Ubuntu 24.04).
- NVIDIA GPU with at least 6 GB VRAM (8 GB recommended), 16 GB RAM, 35 GB free
  disk (the CARLA image alone is 29 GB).
- NVIDIA driver (`nvidia-smi` works), Docker Engine 24+ with the `docker compose`
  v2 plugin (v2.24 or newer), and the
  [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
  configured for Docker:

  ```bash
  sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
  docker run --rm --gpus all ubuntu:24.04 nvidia-smi   # must print your GPU
  ```

- Your user in the `docker` group.
- [Tailscale](https://tailscale.com/download), logged into the team tailnet.
- OpenSSH server, key-only. In `/etc/ssh/sshd_config` (or a drop-in under
  `/etc/ssh/sshd_config.d/`):

  ```
  PasswordAuthentication no
  KbdInteractiveAuthentication no
  PubkeyAuthentication yes
  ```

  then `sudo systemctl restart ssh`.

### Guest (any laptop)

- Any OS. **Docker is not needed on a guest laptop.**
- [VS Code](https://code.visualstudio.com/) with the *Remote - SSH* extension.
- [Foxglove](https://foxglove.dev/download) desktop app.
- [Tailscale](https://tailscale.com/download), logged into the team tailnet.
- An SSH key: `ssh-keygen -t ed25519`.

## Setup on a host

```bash
git clone <this-repo> dedalus-devenv
cd dedalus-devenv
cp .env.example .env
# edit .env: COMPOSE_PROJECT_NAME=dedalus-<your-name>, ROS_DOMAIN_ID,
#            WS_PATH, BAGS_PATH, HOST_UID/HOST_GID (id -u / id -g),
#            COMPOSE_PROFILES=sim   (host only: this starts CARLA)
mkdir -p ws/src bags          # only if you keep the default WS_PATH / BAGS_PATH
docker compose build ros2     # builds dedalus-devenv:jazzy, a few minutes
docker compose up -d --wait   # pulls CARLA (29 GB) the first time, waits until it
                              # answers on :2000, then starts your ros2
docker compose exec ros2 bash # a shell in the ROS 2 container
```

### First run (smoke test)

`smoke/carla_bridge_minimal.py` is a stand-alone CARLA <-> ROS 2 node: it puts
CARLA in synchronous mode, ticks it at 20 Hz, spawns one car and publishes
`/clock` and `/ground_truth/odom`. No sensors, no project code, so the only
things that can fail are CARLA and the connection to it. Inside the container
(`docker compose exec ros2 bash`):

```bash
# host (CARLA via the sim profile) and guest (the host's CARLA):
python3 /smoke/carla_bridge_minimal.py --ros-args -p autopilot:=true

# Docker Desktop with CARLA running natively on the laptop:
python3 /smoke/carla_bridge_minimal.py --ros-args -p autopilot:=true -p carla_host:=host.docker.internal
```

Weak GPU (2-4 GB VRAM) or laptop, from the script header:

- Smallest map: add `-p map:=Town02`.
- Lightest test, server rendering off: add `-p no_rendering:=true`.
- `follow_camera` stays off (default). Moving the spectator every tick streams
  new scenery into GPU memory and crashes CARLA on small cards.
- Launch CARLA with a fixed small window and never resize it while it runs
  (`CarlaUE4 -windowed -ResX=800 -ResY=600`); resizing triggers GPU page faults.
  Headless (`-RenderOffScreen`, as in `compose.yml`) avoids this entirely.

Success criteria:

- The node prints `t / x / y / v / RTF` once per second, with RTF close to 1.0
  and `v` different from 0 (the Traffic Manager is driving the car).
- In a second `docker compose exec ros2 bash`, `ros2 topic hz /ground_truth/odom`
  shows about 20 Hz.

Stop the node with Ctrl-C; it hands the world back to asynchronous mode.

Every shell in the container already has ROS 2 sourced and, if present,
`/ws/install/setup.bash`. The alias `cs` runs `colcon build --symlink-install`
in `/ws` and re-sources the workspace.

Stop your containers with `docker compose down`. This only touches your own
compose project; guests' containers are separate projects.

### Pointing at your own workspace

Set `WS_PATH` in `.env` to the directory that contains your `src/` folder
(for example `WS_PATH=/home/anna/ros2_ws`). It is mounted at `/ws`, so
`colcon build` inside the container writes `build/`, `install/`, `log/` next to
your `src/` on the host, owned by your user (`HOST_UID`/`HOST_GID`). The
DEDALUS source lives in that workspace, not here.

`BAGS_PATH` is mounted at `/bags` for `ros2 bag record -o /bags/<name>`.

## Remote guests

Names below: `<host>` is the Linux user name on the host PC, `<guest>` is the
guest's name.

### Once, on the host (done by the host owner)

1. Receive the guest's public key (`~/.ssh/id_ed25519.pub` on the guest laptop)
   and append it:

   ```bash
   echo '<contents of id_ed25519.pub>' >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   ```

2. Create the guest's folders:

   ```bash
   mkdir -p /home/<host>/<guest>/ws/src /home/<host>/<guest>/bags
   ```

3. Tell the guest the host's Tailscale IP (`tailscale ip -4`) and the host user
   name. The guest logs in *as the host user*; separation between people is by
   folder and compose project, not by Linux account.

### Once, on the guest laptop

Add the host to `~/.ssh/config` (create the file if needed):

```
Host dedalus-<host>
    HostName <tailscale-ip-of-host>
    User <host>
    IdentityFile ~/.ssh/id_ed25519
    LocalForward 8765 localhost:8765
```

`LocalForward` tunnels the host's port 8765 (foxglove_bridge) to the laptop.
Check with `ssh dedalus-<host>`.

### Every session

1. In VS Code: *Remote-SSH: Connect to Host...* → `dedalus-<host>`. VS Code
   now runs on the host; open the folder `/home/<host>/<guest>/`.
2. First time only, in the VS Code terminal (which is a shell on the host):

   ```bash
   cd /home/<host>/<guest>
   git clone <this-repo> dedalus-devenv
   cd dedalus-devenv
   cp .env.example .env
   ```

   and set in `.env`:

   ```
   COMPOSE_PROJECT_NAME=dedalus-<guest>
   ROS_DOMAIN_ID=<a number nobody else on this host uses>
   COMPOSE_PROFILES=
   WS_PATH=/home/<host>/<guest>/ws
   BAGS_PATH=/home/<host>/<guest>/bags
   HOST_UID=<id -u on the host>
   HOST_GID=<id -g on the host>
   ```

   The image is already built on the host, so no `docker compose build` is needed.
3. Start your own ROS 2 container and get a shell in it:

   ```bash
   docker compose up -d ros2
   docker compose exec ros2 bash
   ```

   With `COMPOSE_PROFILES` empty the `carla` service is not part of your
   project: your `ros2` starts on its own and uses the host's CARLA on
   `localhost:2000`.
4. Foxglove on your laptop: *Open connection* → Foxglove WebSocket →
   `ws://localhost:8765`. It reaches the host through the SSH tunnel, so keep
   the VS Code / SSH session open.
5. When done: `docker compose down` (only your containers).

Two people on one host must not both run foxglove_bridge on 8765 (host
networking, one port). Agree on a port per person, start the bridge with
`port:=<your-port>`, and put that port in your `LocalForward` line
(`LocalForward 8765 localhost:<your-port>`); Foxglove on the laptop still uses
`ws://localhost:8765`.

## Host notes

- The host starts CARLA (`COMPOSE_PROFILES=sim`). **Only one CARLA per machine**:
  port 2000 and the simulated world are shared by everyone on that host. Agree
  before resetting the world or changing the map. To start or stop just the
  simulator:

  ```bash
  docker compose --profile sim up -d --wait carla
  docker compose --profile sim stop carla
  ```

- Different `COMPOSE_PROJECT_NAME` per person, otherwise you replace each
  other's containers. Different `ROS_DOMAIN_ID` per person, otherwise your ROS
  graphs merge.
- SSH is only needed while guests are working. Outside sessions the host can
  turn it off:

  ```bash
  sudo systemctl stop ssh.socket ssh.service     # off
  sudo systemctl start ssh.socket                # on again
  ```

- Foxglove over the tunnel: subscribe to **compressed** image topics
  (`.../compressed`, `image_transport` plugins are in the image). Raw camera
  streams do not fit over Wi-Fi.

### GUI tools on the host (rviz2, rqt, CARLA with a window)

The containers get `DISPLAY` and the X11 socket. Allow local Docker clients
once per login on the host:

```bash
xhost +local:docker
```

## Smoke tests

Inside the container (`docker compose exec ros2 bash`):

```bash
ros2 topic list
python3 -c "import carla; print(carla.Client('localhost', 2000).get_server_version())"
```

The second command prints `0.9.16` when the client can talk to the simulator.
ROS 2 is sourced by `.bashrc`, which only interactive shells read. For one-off
commands from the host use an interactive shell:
`docker compose exec ros2 bash -ic 'ros2 topic list'`.
Check the ROS 2 settings with `printenv ROS_DOMAIN_ID RMW_IMPLEMENTATION`
(expected: your domain ID and `rmw_fastrtps_cpp`).

## Design rules

- **One ROS distribution, one middleware.** Jazzy and Fast DDS are fixed in the
  image (`RMW_IMPLEMENTATION=rmw_fastrtps_cpp`). Do not switch middleware per
  machine; a mixed graph does not discover reliably.
- **CARLA client == CARLA server version.** `CARLA_VERSION` in `.env` must stay
  `0.9.16` unless the `carla` pip package in the Dockerfile is changed with it.
- **No code in the image.** Dependencies are listed explicitly in the
  Dockerfile. If a new node needs a new `ros-jazzy-*` or pip package, add it
  there and rebuild; do not `docker commit` a container.
- The `ros2` container runs as UID/GID from `.env` with `HOME=/home/ubuntu`, so
  anything written to `/ws` or `/bags` belongs to you on the host.

## Optional: local bag replay on a guest laptop (Docker Desktop)

Not needed for normal work. If you want to replay bags on your own
Windows/macOS laptop without a host, install Docker Desktop and use the
override file, which removes host networking, the GPU and the CARLA service and
publishes foxglove_bridge on `8765`:

```bash
cp .env.example .env            # COMPOSE_PROFILES empty, WS_PATH/BAGS_PATH to local folders
docker compose -f compose.yml -f compose.desktop.yml build ros2
docker compose -f compose.yml -f compose.desktop.yml up -d
docker compose -f compose.yml -f compose.desktop.yml exec ros2 bash
```

There is no CARLA in this mode. The override needs Docker Compose v2.24 or
newer (it uses `!reset` / `!override`).

## Files

```
compose.yml           carla + ros2 services (Linux hosts, host network, GPU)
compose.desktop.yml   override for optional bag replay on Docker Desktop
docker/ros2/Dockerfile
smoke/carla_bridge_minimal.py   stand-alone CARLA <-> ROS 2 smoke test, mounted read-only at /smoke
.env.example          copy to .env; .env is git-ignored
```

# carla_bridge_minimal: the smallest CARLA <-> ROS 2 bridge, for testing a new computer.
#
# What it does, and nothing more:
#   1. connects to a running CARLA server and loads a map
#   2. puts CARLA in synchronous mode: the world moves only when this node calls world.tick()
#   3. a ROS timer calls world.tick() every tick_period seconds of real time (20 Hz loop)
#   4. spawns one car; with autopilot:=true CARLA's Traffic Manager drives it
#   5. after every tick publishes /clock (simulation time) and /ground_truth/odom (true pose)
#
# No sensors, no command input, no custom messages: only standard ROS 2 packages (rclpy,
# rosgraph_msgs, nav_msgs, tf2_ros), so the only things that can fail are CARLA itself and
# the connection to it. Once this runs, the full carla_bridge is the next step.
#
# Run:
#   terminal 1: CARLA server   (Windows: CarlaUE4.exe,  Linux: ./CarlaUE4.sh)
#   terminal 2: python3 carla_bridge_minimal.py --ros-args -p autopilot:=true
#   CARLA on the Windows host, this node inside a Docker container:
#               ... --ros-args -p autopilot:=true -p carla_host:=host.docker.internal
#
# Weak GPU (2-4 GB VRAM) and laptops: what crashes CARLA and what to do instead
#   - follow_camera is OFF by default. Moving the spectator every tick makes the server keep
#     streaming new scenery into GPU memory; on a 2 GB card this crashes CARLA within seconds.
#     Switch it on only on a GPU with 6 GB or more:   -p follow_camera:=true
#   - Start CARLA with a fixed, small window and NEVER resize it while it runs (resizing, or a
#     very small window, triggers GPU page faults):   CarlaUE4 -windowed -ResX=800 -ResY=600
#   - -quality-level=Low worked on Windows laptops. On Linux with Town10HD it crashed (UE4
#     landscape texture bug); there use Epic quality and run headless:   -RenderOffScreen
#   - Smallest map:                                   -p map:=Town02
#   - Lightest possible test, rendering switched off on the server (window goes black, physics
#     and this bridge keep working; cameras would give no images, this script has none):
#                                                     -p no_rendering:=true
#
# Coordinates: CARLA is left-handed (y right, yaw clockwise, degrees); ROS is right-handed.
#   positions:  y -> -y
#   yaw:        sign flipped, degrees -> radians

import math
import time
import carla
import rclpy
from rclpy.executors import ExternalShutdownException
from builtin_interfaces.msg import Time
from rosgraph_msgs.msg import Clock
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster


def main():
    # ------------------------------------------------------------------
    # ROS node and parameters
    # ------------------------------------------------------------------
    rclpy.init()
    node = rclpy.create_node("carla_bridge_minimal")
    node.declare_parameter("carla_host", "localhost")   # where the CARLA server runs
    node.declare_parameter("map", "Town10HD")           # project default; Town02 is the smallest
    node.declare_parameter("tick_period", 0.05)         # [s] real time between two ticks
    node.declare_parameter("autopilot", False)          # true: Traffic Manager drives the car
    node.declare_parameter("follow_camera", False)      # move the spectator behind the car (needs >= 6 GB VRAM)
    node.declare_parameter("no_rendering", False)       # true: server renders nothing (weakest GPUs)

    host = node.get_parameter("carla_host").value
    map_name = node.get_parameter("map").value
    tick_period = node.get_parameter("tick_period").value
    autopilot = node.get_parameter("autopilot").value
    follow_camera = node.get_parameter("follow_camera").value
    no_rendering = node.get_parameter("no_rendering").value

    clock_pub = node.create_publisher(Clock, "/clock", 10)
    gt_pub = node.create_publisher(Odometry, "/ground_truth/odom", 10)
    tf_pub = TransformBroadcaster(node)

    # ------------------------------------------------------------------
    # CARLA: connect, load the map, synchronous mode
    # ------------------------------------------------------------------
    # 60 s timeout: loading a map for the first time can take long on a laptop.
    # If this fails, the server is not reachable (not running, wrong host, firewall).
    client = carla.Client(host, 2000)
    client.set_timeout(60.0)
    print("connecting to CARLA at", host, "... server version:", client.get_server_version())
    world = client.load_world(map_name)

    # Synchronous mode: the world only moves on world.tick(), and every tick is exactly 0.05 s.
    # The Traffic Manager must be synchronous too, otherwise the autopilot stalls.
    # no_rendering_mode: the server skips all rendering; physics and the RPC interface still run.
    original_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    settings.no_rendering_mode = no_rendering
    world.apply_settings(settings)

    tm = client.get_trafficmanager(8000)
    tm.set_synchronous_mode(True)

    # One car at the first spawn point of the map
    blueprint = world.get_blueprint_library().find("vehicle.tesla.model3")
    spawn_point = world.get_map().get_spawn_points()[0]
    ego = world.spawn_actor(blueprint, spawn_point)
    if autopilot:
        ego.set_autopilot(True, tm.get_port())

    spectator = world.get_spectator()
    start_wall = time.time()
    start_sim = world.get_snapshot().timestamp.elapsed_seconds

    # ------------------------------------------------------------------
    # One simulation step. Called by ROS every tick_period seconds of REAL time.
    # ------------------------------------------------------------------
    def on_timer():
        # 0) Advance the world by one step (0.05 s of simulation time)
        frame = world.tick()

        # 1) Time stamp from the SIMULATION clock, published on /clock
        t = world.get_snapshot().timestamp.elapsed_seconds
        stamp = Time()
        stamp.sec = int(t)
        stamp.nanosec = int((t - int(t)) * 1e9)

        clock_msg = Clock()
        clock_msg.clock = stamp
        clock_pub.publish(clock_msg)

        # 2) True pose of the car: CARLA (left-handed, degrees) -> ROS (right-handed, radians)
        pose = ego.get_transform()
        x = pose.location.x
        y = -pose.location.y
        z = pose.location.z
        yaw = -math.radians(pose.rotation.yaw)

        # Viewer camera 8 m behind and 4 m above the car (CARLA coordinates, only for watching).
        # Off by default: see the weak-GPU notes at the top.
        if follow_camera:
            forward = pose.get_forward_vector()
            cam_location = pose.location - 8.0 * forward + carla.Location(z=4.0)
            cam_rotation = carla.Rotation(pitch=-15.0, yaw=pose.rotation.yaw)
            spectator.set_transform(carla.Transform(cam_location, cam_rotation))

        # 3) Forward speed: velocity in the map frame, projected on the car's heading
        vel = ego.get_velocity()
        vx_map = vel.x
        vy_map = -vel.y
        v_forward = vx_map * math.cos(yaw) + vy_map * math.sin(yaw)

        # 4) Heading as a quaternion (flat ground: rotation about z only)
        qz = math.sin(yaw / 2.0)
        qw = math.cos(yaw / 2.0)

        # 5) Ground-truth odometry message
        odom = Odometry()
        odom.header.stamp = stamp
        odom.header.frame_id = "map"
        odom.child_frame_id = "base_link_gt"
        odom.pose.pose.position.x = x
        odom.pose.pose.position.y = y
        odom.pose.pose.position.z = z
        odom.pose.pose.orientation.z = qz
        odom.pose.pose.orientation.w = qw
        odom.twist.twist.linear.x = v_forward
        gt_pub.publish(odom)

        # 6) Same pose as a TF transform map -> base_link_gt (so Foxglove can draw the car)
        tf = TransformStamped()
        tf.header.stamp = stamp
        tf.header.frame_id = "map"
        tf.child_frame_id = "base_link_gt"
        tf.transform.translation.x = x
        tf.transform.translation.y = y
        tf.transform.translation.z = z
        tf.transform.rotation.z = qz
        tf.transform.rotation.w = qw
        tf_pub.sendTransform(tf)

        # 7) Once per simulated second: print the state and the real-time factor.
        #    RTF = simulated seconds / real seconds. 1.0 = real time; below 1.0 = the PC is too slow.
        if frame % 20 == 0:
            sim_elapsed = t - start_sim
            wall_elapsed = time.time() - start_wall
            rtf = sim_elapsed / wall_elapsed
            print("t =", round(sim_elapsed, 1),
                  "x =", round(x, 1),
                  "y =", round(y, 1),
                  "v =", round(v_forward, 2),
                  "RTF =", round(rtf, 2))

    node.create_timer(tick_period, on_timer)
    print("carla_bridge_minimal running: map =", map_name,
          ", tick_period =", tick_period, "s, autopilot =", autopilot,
          ", follow_camera =", follow_camera, ", no_rendering =", no_rendering)

    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        # Shutdown order: autopilot off, original settings back (async mode, rendering on), destroy the car
        ego.set_autopilot(False, tm.get_port())
        world.apply_settings(original_settings)
        tm.set_synchronous_mode(False)
        ego.destroy()
        node.destroy_node()
        rclpy.try_shutdown()
        print("bridge stopped, settings restored")


if __name__ == "__main__":
    main()

import os

import time

import boto3

from datetime import datetime

# Read environment variables

aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")

aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")

aws_session_token = os.getenv("AWS_SESSION_TOKEN")

aws_region = os.getenv("AWS_DEFAULT_REGION")

instance_input = os.getenv("INSTANCE_INPUT")  # e.g., "i-1234abcd:t3.medium,i-5678efgh:t3.large"

change_number = os.getenv("CHANGE_NUMBER")

# Initialize boto3 session

session = boto3.Session(

    aws_access_key_id=aws_access_key,

    aws_secret_access_key=aws_secret_key,

    aws_session_token=aws_session_token,

    region_name=aws_region

)

ec2 = session.client('ec2')

# Prepare logging

log_file = f"{change_number}.log"

def log(msg):

    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

    with open(log_file, "a") as f:

        f.write(f"{timestamp} {msg}\n")

    print(f"{timestamp} {msg}")

# Parse instance inputs

instance_map = dict(item.split(":") for item in instance_input.split(","))

for instance_id, new_type in instance_map.items():

    log(f"Processing instance {instance_id} → {new_type}")

    # Get current instance info

    res = ec2.describe_instances(InstanceIds=[instance_id])

    instance = res["Reservations"][0]["Instances"][0]

    old_type = instance["InstanceType"]

    volume_ids = [bdm["Ebs"]["VolumeId"] for bdm in instance["BlockDeviceMappings"]]

    log(f"Current instance type: {old_type}")

    log(f"Volumes attached: {volume_ids}")

    # Get volume tags and create snapshots

    snapshot_ids = []

    for vol_id in volume_ids:

        vol_info = ec2.describe_volumes(VolumeIds=[vol_id])["Volumes"][0]

        tags = vol_info.get("Tags", [])

        tags.append({"Key": "change", "Value": change_number})

        description = "snapshot before the change"

        snapshot = ec2.create_snapshot(VolumeId=vol_id, Description=description, TagSpecifications=[

            {"ResourceType": "snapshot", "Tags": tags}

        ])

        snapshot_ids.append(snapshot["SnapshotId"])

        log(f"Created snapshot {snapshot['SnapshotId']} for volume {vol_id}")

    # Monitor snapshot progress every 5 minutes

    completed = set()

    while len(completed) < len(snapshot_ids):

        log("Checking snapshot progress...")

        for snap_id in snapshot_ids:

            if snap_id in completed:

                continue

            snap = ec2.describe_snapshots(SnapshotIds=[snap_id])["Snapshots"][0]

            prog = snap.get("Progress", "0%")

            log(f"Snapshot {snap_id}: {prog}")

            if snap["State"] == "completed":

                completed.add(snap_id)

        if len(completed) < len(snapshot_ids):

            log("Waiting 5 minutes before next snapshot check...")

            time.sleep(300)

    log("All snapshots completed.")

    # Stop instance

    log(f"Stopping instance {instance_id}...")

    ec2.stop_instances(InstanceIds=[instance_id])

    ec2.get_waiter("instance_stopped").wait(InstanceIds=[instance_id])

    log(f"Instance {instance_id} stopped.")

    # Modify instance type

    log(f"Changing instance type from {old_type} to {new_type}")

    try:

        ec2.modify_instance_attribute(InstanceId=instance_id, InstanceType={"Value": new_type})

        log("Instance type modified.")

    except Exception as e:

        log(f"Error changing instance type: {e}")

        continue

    # Start instance

    log(f"Starting instance {instance_id}...")

    ec2.start_instances(InstanceIds=[instance_id])

    ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id])

    log("Instance is running.")

    # Wait for system + instance + EBS checks to pass

    log("Waiting for 3/3 status checks...")

    while True:

        status = ec2.describe_instance_status(InstanceIds=[instance_id], IncludeAllInstances=True)["InstanceStatuses"]

        if not status:

            time.sleep(10)

            continue

        inst_status = status[0]["InstanceStatus"]["Status"]

        sys_status = status[0]["SystemStatus"]["Status"]

        ebs_status = status[0].get("Details", [])

        ebs_pass = all(d["Status"] == "passed" for d in ebs_status if d["Name"] == "reachability")

        if inst_status == "ok" and sys_status == "ok" and ebs_pass:

            log("All 3/3 checks passed.")

            break

        log("Status checks pending... waiting 1 minute.")

        time.sleep(60)

    log(f"Finished resizing instance {instance_id}: {old_type} → {new_type}")

log("All instance changes completed.")
 

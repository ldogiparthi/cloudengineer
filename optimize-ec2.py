import boto3
import os
import time
import sys
# --- Logging to file with change number as filename ---
class Tee:
   def __init__(self, *files):
       self.files = files
   def write(self, obj):
       for f in self.files:
           f.write(obj)
           f.flush()
   def flush(self):
       for f in self.files:
           f.flush()
change_number = os.environ.get("CHANGE_NUMBER", "unknown")
log_filename = f"{change_number}.log"
log_file = open(log_filename, "w")
sys.stdout = Tee(sys.stdout, log_file)
# --- AWS Clients ---
ec2_client = boto3.client("ec2")
ec2_resource = boto3.resource("ec2")
# --- Helpers ---
def get_instance_details(instance_id):
   response = ec2_client.describe_instances(InstanceIds=[instance_id])
   instance = response["Reservations"][0]["Instances"][0]
   instance_type = instance["InstanceType"]
   boot_mode = instance.get("BootMode", "legacy-bios")
   return instance_type, boot_mode
def validate_instance_type(instance_id, new_instance_type):
   old_instance_type, boot_mode = get_instance_details(instance_id)
   info = ec2_client.describe_instance_types(InstanceTypes=[new_instance_type])
   supported = info["InstanceTypes"][0].get("SupportedBootModes", ["legacy-bios"])
   if boot_mode not in supported:
       print(f"❌ ERROR: Instance {instance_id} boot mode '{boot_mode}' not supported by '{new_instance_type}' ({supported})")
       return False
   return True
def take_snapshots(instance_id, change_number):
   instance = ec2_resource.Instance(instance_id)
   snapshots = {}
   for volume in instance.volumes.all():
       description = "Snapshot before the change"
       print(f"📸 Creating snapshot for volume {volume.id} with description: '{description}'")
       snapshot = ec2_client.create_snapshot(
           VolumeId=volume.id,
           Description=description,
           TagSpecifications=[{
               "ResourceType": "snapshot",
               "Tags": volume.tags + [{"Key": "change", "Value": change_number}] if volume.tags else [{"Key": "change", "Value": change_number}]
           }]
       )
       snapshots[snapshot["SnapshotId"]] = volume.id
   return snapshots
def monitor_snapshots(snapshots):
   print("⏳ Monitoring snapshot progress every 5 minutes...")
   while snapshots:
       time.sleep(300)
       response = ec2_client.describe_snapshots(SnapshotIds=list(snapshots.keys()))
       for snap in response["Snapshots"]:
           sid, progress, state = snap["SnapshotId"], snap["Progress"], snap["State"]
           print(f"📊 Snapshot {sid} ({snapshots[sid]}): {progress} - {state}")
           if state == "completed":
               del snapshots[sid]
   print("✅ All snapshots completed.")
def resize_instance(instance_id, new_type):
   old_type, _ = get_instance_details(instance_id)
   print(f"ℹ️ Instance {instance_id} current type: {old_type}")
   if not validate_instance_type(instance_id, new_type):
       return old_type, "Skipped"
   print(f"🛑 Stopping instance {instance_id}...")
   ec2_client.stop_instances(InstanceIds=[instance_id])
   ec2_client.get_waiter("instance_stopped").wait(InstanceIds=[instance_id])
   print(f"✅ Instance stopped.")
   print(f"⚙️ Modifying instance type to {new_type}...")
   ec2_client.modify_instance_attribute(InstanceId=instance_id, InstanceType={"Value": new_type})
   print(f"▶️ Starting instance...")
   ec2_client.start_instances(InstanceIds=[instance_id])
   return old_type, "Resized"
def check_instance_status(instance_id):
   print(f"🩺 Waiting for instance {instance_id} to pass health checks...")
   while True:
       time.sleep(60)
       statuses = ec2_client.describe_instance_status(InstanceIds=[instance_id], IncludeAllInstances=True)["InstanceStatuses"]
       if not statuses:
           print("...still initializing")
           continue
       s = statuses[0]
       sys_status = s["SystemStatus"]["Status"]
       inst_status = s["InstanceStatus"]["Status"]
       vol_status = all(vol["State"] == "in-use" for vol in ec2_client.describe_volumes(Filters=[{"Name": "attachment.instance-id", "Values": [instance_id]}])["Volumes"])
       print(f"✔️ System: {sys_status}, Instance: {inst_status}, EBS: {'ok' if vol_status else 'initializing'}")
       if sys_status == inst_status == "ok" and vol_status:
           break
   print(f"✅ Instance {instance_id} passed all checks.")
# --- Main Flow ---
def main():
   instance_input = os.environ.get("INSTANCE_INPUT")
   change_number = os.environ.get("CHANGE_NUMBER")
   if not instance_input or not change_number:
       print("❌ Required: INSTANCE_INPUT and CHANGE_NUMBER")
       return
   instance_map = dict(x.split(":") for x in instance_input.split(","))
   summary = []
   for iid, itype in instance_map.items():
       print(f"\n=== Resizing {iid} to {itype} ===")
       snaps = take_snapshots(iid, change_number)
       monitor_snapshots(snaps)
       old_type, result = resize_instance(iid, itype)
       if result == "Resized":
           check_instance_status(iid)
       summary.append((iid, old_type, itype, result))
   print("\n--- SUMMARY ---")
   print("Instance ID       Old Type     New Type     Result")
   print("--------------------------------------------------")
   for row in summary:
       print(f"{row[0]:<17} {row[1]:<12} {row[2]:<12} {row[3]}")
   print("--------------------------------------------------")
if __name__ == "__main__":
   main()

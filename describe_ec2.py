import boto3
import os

def describe_instance(instance_id):
    ec2 = boto3.client(
        'ec2',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        aws_session_token=os.getenv('AWS_SESSION_TOKEN')
    )
    
    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
        instance = response['Reservations'][0]['Instances'][0]
        
        print(f"Instance ID: {instance['InstanceId']}")
        print(f"Instance Type: {instance['InstanceType']}")
        print(f"Public IP: {instance.get('PublicIpAddress', 'N/A')}")
        print(f"Private IP: {instance['PrivateIpAddress']}")
        print(f"State: {instance['State']['Name']}")
        print(f"Launch Time: {instance['LaunchTime']}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    instance_id = input("Please enter the instance ID: ")
    describe_instance(instance_id)

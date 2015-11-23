#!/usr/bin/python
# -*- coding: utf-8 -*-

import ConfigParser,  StringIO, logging, Queue, sys, threading, pprint
import boto3, botocore.exceptions
import datetime, time
from dateutil.tz import tzlocal, tzutc

# photographer.py
#
#    Author: Joe Beard <joe.beard@4a42.org>
#
#    This program is designed to take backups of AWS assets each time it is run and
#    selectively retain backups based on a policy. The policy can define the following:
#       Number of most recent backups to be held (including the backup taken on this run)
#       Number of days to hold the oldest backup for each day
#       Number of 7 day periods to hold the oldest backup for each period (weeks)
#       Number of 31 day periods to hold the oldest backup for each period (months)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License version 3, as
#    published by the Free Software Foundation.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#    This lambda script has the following configuration requirements:
#    * Run with a IAM role that has the following permissions
#      * Access config file in S3
#      * describe ec2 instances
#      * Send email using SES
#    * Scheduled to run periodically (it will not react to the event info supplied)
#    * Timeout may need to be increased depending on the number of objects to be backed up


logging_level = logging.INFO
dry_run = False

s3_bucket = '4a42-ops'
s3_file = 'photographer.conf'

# dates_to_keep
#
# This function takes an array of datetime.datetime objects and returns only those which have been selected to be
# retained based on the following rules:
#   most_recent of the most recent dates
#   the oldest date for each day in the last 'days'
#   the oldest date for each 7 day period in the last 'weeks', oldest in each now+7x to now+7(x+1) for x in range 0 to weeks
#   the oldest date for each 31 day period in the last 'months'
#
# It should be noted with the months field, this is not strictly months as it is a 31 day period
#
def dates_to_keep(dates = None, retention_limits=None, now_time=datetime.datetime.now(tzutc())):
    
    defaults = {'most_recent':{'default':5},
                'days'  :{'default':7, 'number_of_days':1 },
                'weeks' :{'default':4, 'number_of_days':7 },
                'months':{'default':6, 'number_of_days':31}
                }
    
    now_time =  datetime.datetime.strptime(now_time.strftime("%Y-%m-%d"), "%Y-%m-%d")
    
    if retention_limits is None:
        retention_limits = {}
    if dates is None:
        return []
    
    #check if dates are tz aware:
    if dates[0].tzinfo is not None:
        now_time = datetime.datetime(now_time.year, now_time.month, now_time.day, tzinfo=tzutc())

    date_selection = dict([(date, False) for date in dates])
    
    #mark up the most recent required.
    dates.sort()
    for date in dates[-retention_limits.get('most_recent', defaults['most_recent']['default']):]:
        date_selection[date] = True

    # For each limit (days, weeks, months), step through the limit, finding days in scope and marking
    # the oldest as to be retained.
    for limit in ['days','weeks','months']:
        for day in range(0, retention_limits.get(limit,  defaults[limit]['default']) ):
            start_time = now_time-datetime.timedelta(days=day*defaults[limit]['number_of_days'])
            end_time = now_time-datetime.timedelta(days=(day-1)*defaults[limit]['number_of_days'])
            try:
                dates_in_scope = [date for date in date_selection if  start_time <= date < end_time]
            except Exception:
                print now_time, start_time, end_time
                raise AttributeError()
            try:
                oldest_backup_in_scope = min(dates_in_scope)
                date_selection[oldest_backup_in_scope] = True   
            except ValueError as e:
                pass
        
    returning_dates = [date for date in date_selection if date_selection[date] is True]
    
    return returning_dates



# threaded
#
#Decorator to script to be multi-threaded
def threaded(fn):
    def wrapper(*args, **kwargs):
        threading.Thread(target=fn, args=args, kwargs=kwargs).start()
    return wrapper



# load_config
#
# take a text file held in an S3 Bucket and load it into a ConfigParser object.
def load_config(bucket=None, key=None):
    if bucket is None or key is None:
        raise AttributeError('Boom')
        
    
    try:
        client = boto3.client('s3')
        r = client.get_object(Bucket=bucket,Key=key)
    except botocore.exceptions.ClientError as e: 
        client = boto3.client('s3')
        location = client.get_bucket_location(Bucket=bucket)[u'LocationConstraint']
        session = boto3.session.Session(region_name=location)
        client = session.client('s3', config= boto3.session.Config(signature_version='s3v4'))
        r = client.get_object(Bucket=bucket,Key=key)

    s = ''
    chunk = r[u'Body'].read(1024*8)
    while chunk:
        s += chunk
        chunk = r[u'Body'].read(1024*8)
    configparser = ConfigParser.ConfigParser()
    configparser.readfp(StringIO.StringIO(s))
    return configparser



# process_instance
#
# Actions to complete:
#   Take AMI now
#   Find all existing AMIs
#   Remove those not required by policy
#
@threaded
def process_instance_id(policy='Unknown', aws_region=None, instance_id=None, retention_limits=None, ec2_client=None):  
    if aws_region is None or instance_id is None:
        logging.error('%s: Could not process volume for %s-%s' % (policy, aws_region, volume_id))
        return False
    if ec2_client is None:
        ec2_client = boto3.client('ec2', region_name=aws_region)
    
    logging.info('%s: Processing instance %s (%s)' % (policy, instance_id, aws_region))
    try:
        response = ec2_client.describe_instances(InstanceIds=[instance_id,])
    except botocore.exceptions.ClientError as e:
        logging.error('%s: %s' % (policy, e))
        return False
    try:
        instance_data = response[u'Reservations'][0][u'Instances'][0]
        if not instance_id == instance_data[u'InstanceId']:
            raise AttributeError('Wrong Instance Returned')
    except AttributeError as e:
        logging.error('%s: %s' % (policy, e))
        return False
    
    now = datetime.datetime.now(tzlocal())
    try:
        instance_name = [tag[u'Value'] for tag in instance_data.get(u'Tags',[]) if tag[u'Key'] == 'Name'][0]
    except KeyError:
        instance_name = 'Not Named'
    
    #Build Name for AMI:
    ami_name = '%s (%s) %s - Taken by Photographer' % (instance_id, instance_name, now.isoformat())
    ami_name = ami_name[0:128]
    ami_name = "".join([c for c in ami_name if c.isalnum() or c in ' ().-/_'])
    logging.info('%s: %s:%s using name: %s' % (policy, aws_region, instance_id, ami_name))
    
    #Build description for AMI
    ami_description = 'Automatic backup taken by Photographer - Instance Tags at time of image (%s)' % ". ".join(['%s-%s' %(tag[u'Key'], tag[u'Value']) for tag in  instance_data.get(u'Tags',[])])
    ami_description = ami_description[0:255]
    ami_description = "".join([c for c in ami_description if c.isalnum() or c in ' ().-/_'])
    logging.info('%s: %s:%s using description: %s' % (policy, aws_region, instance_id, ami_description[0:255]))
    
    
    #Create AMI
    try:
        response = ec2_client.create_image(DryRun=dry_run, InstanceId=instance_id, Name=ami_name, Description=ami_description, NoReboot=True )
        new_ami_id = response[u'ImageId']

        #Tag AMI
        tags = [{'Key': 'source_instance','Value': instance_id}]
        tags.extend(instance_data.get(u'Tags',[])[0:9])
        ec2_client.create_tags(DryRun=dry_run, Resources=[new_ami_id], Tags=tags)
    except botocore.exceptions.ClientError as e:
        logging.error(e)
        
    # Clean up old AMIs   
    #    
    # This is using the source_instance tag, if multiple Instances share an instance ID over time, 
    # this may result in older Images being deleted.
    # It is assumed there is a relatively low chance of collision.
    
    # Get all existing AMIs of instance.
    response = ec2_client.describe_images(DryRun=False,Owners=['self',],Filters=[{'Name': 'tag:source_instance','Values': [instance_id,]}])
    existing_amis = response[u'Images']
    # Convert to a list of datetimes
    ami_dates = [datetime.datetime.strptime(ami[u'CreationDate'],'%Y-%m-%dT%H:%M:%S.%fZ') for ami in existing_amis]
    # Calculate which datetimes are required to be retained under the retention policy
    retained_dates = dates_to_keep(retention_limits=retention_limits, dates=ami_dates)

    # No check each AMI in turn cleaning up those which are not needed
    for ami in existing_amis:
        # Check if this AMIs date is in the list we want to keep, if not remove it.
        # It must either be the list of dates required by policy or tagged with a retention tag
        
        required_by_date = datetime.datetime.strptime(ami[u'CreationDate'],'%Y-%m-%dT%H:%M:%S.%fZ') in retained_dates
        retention_tag_found = len([tag for tag in ami[u'Tags'] if tag[u'Key'].startswith('retention')]) > 0
        
        if required_by_date or retention_tag_found:
            logging.info('%s: %s:%s keeping: %s' % (policy, aws_region, instance_id, ami[u'Name']))
        else:
            logging.info('%s: %s:%s deleting: %s' % (policy, aws_region, instance_id, ami[u'Name']))
            
            #List out the AMIs associated snapshots so we can remove those once the AMI is deregistered.
            snapshots_to_delete = []
            for block in ami[u'BlockDeviceMappings']:
                snapshots_to_delete.append(block[u'Ebs'][u'SnapshotId'])
             
            try:
                response = ec2_client.deregister_image(DryRun=dry_run,ImageId=ami[u'ImageId'])
                logging.warning('%s: %s:%s deleted: %s - %s' % (policy, aws_region, instance_id, ami[u'Name'], response))
            except botocore.exceptions.ClientError as e:
                logging.error(e)
            
            for snapshot in snapshots_to_delete:
                try:
                    response = ec2_client.delete_snapshot(DryRun=dry_run,SnapshotId=snapshot)
                    logging.warning('%s: %s:%s deleted: %s - %s' % (policy, aws_region, instance_id, snapshot, response))
                except botocore.exceptions.ClientError as e:
                    logging.error(e)
    

    
# process_volume
#
# Actions to complete:
#   Take snapshot now
#   Find existing snapshots
#   Remove those not required by policy
#
@threaded
def process_volume_id(policy='Unknown', aws_region=None, volume_id=None, retention_limits=None, ec2_client=None): 
    if aws_region is None or volume_id is None:
        logging.error('%s: Could not process volume for %s-%s' % (policy, aws_region, volume_id))
        return False
    if ec2_client is None:
        ec2_client = boto3.client('ec2', region_name=aws_region)
    
    logging.info('%s: Processing Volume of %s (%s)' % (policy, volume_id, aws_region))
    
    # Make sure the volume actually exists and collect data to name the snapshot.
    try: 
        response = ec2_client.describe_volumes(DryRun=False, VolumeIds=[volume_id])
        volume_data = response[u'Volumes'][0]
    except botocore.exceptions.ClientError as e:
        logging.error('%s: %s - %s' % (policy, volume_id, e))
        return False
    
    # Build a sensible description
    if len(volume_data[u'Attachments']) > 0:
        attachment = volume_data[u'Attachments'][0]
        attachment_description = "Attached to %s:%s" % (attachment[u'InstanceId'], attachment[u'InstanceId'])
    else:
        attachment_description = 'Not Attached'
    description = 'Created by Photographer(%s) - %s' % (volume_id, attachment_description)

    # Take the snapshot and tag it appropriately
    try: 
        response = ec2_client.create_snapshot(DryRun=dry_run, VolumeId=volume_id, Description=description)
        snapshot_id = response[u'SnapshotId']
        ec2_client.create_tags(DryRun=False, Resources=[snapshot_id], Tags=volume_data[u'Tags'])
    except botocore.exceptions.ClientError as e:
        logging.error('%s: %s - %s' % (policy, volume_id, e))
        return False  
    
    # Find all the snapshots for the current volume
    response = ec2_client.describe_snapshots(OwnerIds=['self'],Filters=[{'Name':'volume-id','Values':[volume_id]}])
    #Filter for only those created by photograpgher
    existing_snapshots = [ss for ss in response[u'Snapshots'] if ss[u'Description'].startswith('Created by Photographer')]
    # Build to a list of datetimes
    snapshot_dates = [ss[u'StartTime'] for ss in existing_snapshots]
    # Calculate which datetimes are required to be retained under the retention policy
    retained_dates = dates_to_keep(retention_limits=retention_limits, dates=snapshot_dates)

    # Now check each Snapshot in turn cleaning up those which are not needed
    for snapshot in existing_snapshots:
        # Check if this AMIs date is in the list we want to keep, if not remove it.
        # It must either be the list of dates required by policy or tagged with a retention tag
        required_by_date = snapshot[u'StartTime'] in retained_dates
        retention_tag_found = len([tag for tag in snapshot.get(u'Tags',[]) if tag[u'Key'].startswith('retention')]) > 0
        
        if required_by_date or retention_tag_found:
            logging.info('%s: %s:%s keeping %s (Date=%s, Tag=%s)' % (policy, aws_region, volume_id, snapshot[u'Description'], required_by_date, retention_tag_found))
        else:
            logging.info('%s: %s:%s deleting: %s' % (policy, aws_region, volume_id, snapshot[u'Description']))
            
            try:
                response = ec2_client.delete_snapshot(DryRun=dry_run,SnapshotId=snapshot[u'SnapshotId'])
                logging.warning('%s: %s:%s deleted: %s - %s' % (policy, aws_region, volume_id, snapshot, response))
            except botocore.exceptions.ClientError as e:
                logging.error(e)
    

@threaded 
def process_policy(policy = None, cp=None):

            #Get Region
            try:
                aws_region = cp.get(policy, 'aws_region')
                logging.info('%s is operating in %s.' % (policy, aws_region))
            except ConfigParser.NoOptionError as e:
                logging.error('%s does not specify a region, this is required ignoring policy.' % policy)
                return False
            
            aws_regions = ['us-east-1', 'us-west-2', 'us-west-1', 
               'eu-west-1', 'eu-central-1', 'ap-southeast-1', 
               'ap-southeast-2', 'ap-northeast-1', 'sa-east-1']            
            if aws_region not in aws_regions:
                logging.error('%s specified an invalid region (%s), this is required ignoring policy.' % (policy, aws_region))
                return False   
            ec2_client = boto3.client('ec2', region_name=aws_region)
        
            retention_limits = {'most_recent':5,
                                'days':7,
                                'weeks':4,
                                'months':2
                               }
    
            #Get retention limits
            for limit in retention_limits:
                try:
                    retention_limits[limit] = cp.getint(policy, limit)
                except ConfigParser.NoOptionError as e:
                    logging.warning('%s does not declare %s number, assuming default of %s.' % (policy, limit, retention_limits[limit]))

            #Find all assets to be backed up
            #Volumes first
            try:
                volume_ids = cp.get(policy, 'volume_ids')
                if volume_ids == 'None':
                    volume_ids = []
                else:
                    volume_ids = volume_ids.split()
                
            except ConfigParser.NoOptionError as e:
                logging.info('%s has not declared a volume section.' % policy)
                
            for volume_id in volume_ids:
                process_volume_id(policy=policy, aws_region=aws_region, volume_id=volume_id, retention_limits=retention_limits, ec2_client=ec2_client)

            #Instances
            instance_ids = []
            #First take all instances specified by name and convert to InstanceIDs
            try:
                instances_by_name = cp.get(policy, 'instance_names')
                if instances_by_name == 'None':
                    instances_by_name = []
                else:
                    instances_by_name = instances_by_name.split()
                
                response = ec2_client.describe_instances(Filters=[{'Name':'tag:Name','Values':instances_by_name}])
                for reservation in response[u'Reservations']:
                    for instance in reservation[u'Instances']:
                        name = [tag for tag in instance[u'Tags'] if tag['Key'] == 'Name'][0]['Value']
                        logging.info('%s: Found instance %s with name %s.' % (policy, instance[u'InstanceId'], name))
                        instance_ids.append(instance[u'InstanceId'])
                
            except ConfigParser.NoOptionError as e:
                logging.info('%s has not declared any instances by name.' % policy)            
            
            
            
            try:
                instances_by_id = cp.get(policy, 'instance_ids')
                if instances_by_id == 'None':
                    instances_by_id = []
                else: 
                    instance_ids.extend(instances_by_id.split())
                
            except ConfigParser.NoOptionError as e:
                logging.info('%s has not declared any instance by id.' % policy)
                
            
            instance_ids = list(set(instance_ids))
            
            for instance_id in instance_ids:
                process_instance_id(policy=policy, aws_region=aws_region, instance_id=instance_id, retention_limits=retention_limits, ec2_client=ec2_client)

                
    
def lambda_handler(event, context):

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging_level)  

    #load configu file from S3
    cp = load_config(s3_bucket, s3_file)
    #cp = ConfigParser.ConfigParser()
    #cp.read('../config_examples/photographer.conf')

    for section in cp.sections():
        try:
            process_policy(policy = section, cp=cp)
        except Exception as e:
            logging.error('An uncaught exception was thrown passing %s (%s)' % (section, e))
            
    while threading.active_count() > 1:
        logging.debug('Currently active threads: %s' % threading.active_count() )
        time.sleep(0.1)
    
if __name__ == '__main__':
    lambda_handler(None, None)
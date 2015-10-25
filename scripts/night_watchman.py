#!/usr/bin/python
# -*- coding: utf-8 -*-

import ConfigParser, boto3, StringIO, logging, Queue
from pytz import timezone

# night_watchman.py
#
#    Author: Joe Beard <joe.beard@4a42.org>
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
#      * shutdown ec2 instance
#      * Send email using SES
#    * Scheduled to run periodically (it will not react to the event info supplied)
#    * Timeout should be increased to 30s (its time to run is dependent on number of reserved instances)


logging_level = logging.WARN

s3_bucket = 'ignops'
s3_file = 'night_watchman.conf'


#Decorator to script to be multi-threaded
def threaded(fn):
    def wrapper(*args, **kwargs):
        threading.Thread(target=fn, args=args, kwargs=kwargs).start()
    return wrapper


def load_config(bucket=None, key=None):
    if bucket is None or key is None:
        raise AttributeError('Boom')
    client = boto3.client('s3')    
    r = client.get_object(Bucket=bucket,Key=key)
    s = ''
    chunk = r[u'Body'].read(1024*8)
    while chunk:
        s += chunk
        chunk = r[u'Body'].read(1024*8)
    configparser = ConfigParser.ConfigParser()
    configparser.readfp(StringIO.StringIO(s))
    return configparser


@threaded
def process_region(region_name = None, configpasser = None, result_queue = None):
    result_queue.put("Results from %s" % region_name)
    
    


def lambda_handler(event, context):

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging_level)  
    
    #load configu file from S3
    cp = load_config(s3_bucket, s3_file)
    
    global_search_tags =  [tuple(x.split(":")) for x in cp.get('general','search_tags').split()]
    
    datetime(2000, 1, 1, 8, 0, 0, 0, timezone('America/Los_Angeles')).astimezone(timezone('Europe/London'))

    
    
    #Find all instances and ASGs which match the given tags
    found_instances = []
    found_asgs = []
    
    #Build Exclusion lists
    excluded_instances = []
    excluded_asgs []
    
    
    
    
if __name__ == '__main__':
    lambda_handler(None, None)
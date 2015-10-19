# reserved_instance_report.py
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
#      * Describe all Reserved Instances in all regions specified
#      * Send email using SES
#    * Scheduled to run periodically (it will not react to the event info supplied)
#    * Timeout should be increased to 30s (its time to run is dependent on number of reserved instances)
#
#    Customisation
#    * regions - remove any regions you don't required
#    * tags_of_interest - any tags that you would like to appear in the report
#    * red_warning_days - days left to trigger red warning (default 30)
#    * orange_warning_days - days left to trigger orange warning (default 60)
#    * report_title - report title
#    * subject_string - email subject
#    * from_address - address from which report is sent
#    * to_address - address to which report is sent

import json
import boto3
import smtplib
import datetime
from dateutil.tz import tzlocal

print('Loading function')

def list_to_html_table(list):
    header = list[0]
    body = list[1:]
    
    #add header
    html = "<table><tr><th>%s</th></tr>" % ("</th><th>".join(header))
    
    for row in body:
        html += "<tr>"
        html += "<th>%s</th>" % row[0]
        for col in row[1:]:
            html += "<td>%s</td>" % col
        html += "</tr>"
    html += "</table>"
    return html
 
def lambda_handler(event, context):
    
    #Customisations for report Scope
    regions = ['us-east-1', 'us-west-2', 'us-west-1', 
               'eu-west-1', 'eu-central-1', 'ap-southeast-1', 
               'ap-southeast-2', 'ap-northeast-1', 'sa-east-1']
    tags_of_interest = ['product', 'app', 'env', 'role']
    red_warning_days = 30
    orange_warning_days = 180
    
    #Configuration for report sending
    report_title = "Reserved Instance Expiry"
    subject_string = "lambda report - %s" % report_title
    from_address = 'lambda_reporting@example.com'
    to_address = 'devops@example.com'
    ses_region = 'eu-west-1'
    
    #Headers for full report table
    report_list = [['id', 'AZ', 'Type', 'Count', 'Length (years)', 'Time Left',]+tags_of_interest ]
    expired_warning_reservations = []
    red_warning_reservations = []
    orange_warning_reservations = []
            
    for region in regions:
        print "Processing %s" % region
        ec2 = boto3.client('ec2', region_name=region)
        response = ec2.describe_reserved_instances()
        for ri in response['ReservedInstances']:
            time_left = ri[u'End'] - datetime.datetime.now(tzlocal())
            
            if time_left < datetime.timedelta(days=-10):
                pass
            elif time_left < datetime.timedelta(days=0):
                expired_warning_reservations.append([ri[u'ReservedInstancesId'], ri[u'AvailabilityZone'],  time_left])
            elif time_left < datetime.timedelta(days=red_warning_days):
                red_warning_reservations.append([ri[u'ReservedInstancesId'], ri[u'AvailabilityZone'],  time_left])
            elif time_left < datetime.timedelta(days=orange_warning_days):
                orange_warning_reservations.append([ri[u'ReservedInstancesId'], ri[u'AvailabilityZone'], time_left])
            
            #convert tags to dictionary
            tags = {}
            for tag in ri.get('Tags',{}):
                tags[tag['Key']] = tag['Value']
            
            #Add the report row to the list
            row = [ ri[u'ReservedInstancesId'], 
                    ri[u'AvailabilityZone'], 
                    ri[u'InstanceType'], 
                    ri[u'InstanceCount'],
                    ri[u'Duration']/31536000 , 
                    time_left,
                    ]
            
            for tag in tags_of_interest:
                row.append(tags.get(tag,'-'))
            
            if time_left > datetime.timedelta(days=-10):
                report_list.append( row )
     
    #Created text version
    msg = "%s\n" % report_title
    msg += "\n".join(["\t".join([str(cell) for cell in row]) for row in report_list])
    
    #Create HTML Version
    html_msg = '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional = //EN"><html> <head><style type="text/css"> H2 { color:#FF0000; } H3 { color:#FFA500; } </style></head><body><h1>Global Reserved Instance Report</h1>'

    
    if len(red_warning_reservations):
        html_msg+="<h2>Warning the following will expire within %s days!</h2>" % red_warning_days
        for row in red_warning_reservations:
            html_msg += "<p>%s (%s) expires in %s days.</p>" % (row[0], row[1], row[2].days)
    if len(orange_warning_reservations):
        html_msg+="<h3>Warning the following will expire within %s days!</h3>" % orange_warning_days
        for row in orange_warning_reservations:
            html_msg += "<p>%s (%s) expires in %s days.</p>" % (row[0], row[1], row[2].days)
    if len(expired_warning_reservations):
        html_msg+="<h3>The following have expired in the last 10 days.</h3>"
        for row in expired_warning_reservations:
            html_msg += "<p>%s (%s) expired %s days ago</p>" % (row[0], row[1], abs(row[2].days))    
            
    html_msg += "<h4>All Reservations</h4>"
    html_msg += list_to_html_table(report_list)
    html_msg += '</body></html>'
    
    ses = boto3.client('ses', region_name=ses_region)
    ses.send_email( Source= from_address,
                    Destination={
                        'ToAddresses': [ to_address, ],
                        'CcAddresses': [],
                        'BccAddresses': []
                    },
                    Message={
                        'Subject': {'Data': subject_string },
                        'Body': {
                            'Text': {'Data': msg,},
                            'Html': {'Data': html_msg,}
                        }
                    },
                    ReplyToAddresses=[ from_address, ]
                )

    return True
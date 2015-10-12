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

    
    print("Received event: " + json.dumps(event, indent=2))
    
    #Customisations for report Scope
    regions = ['us-east-1','us-west-1','us-west-2','eu-central-1']
    tags_of_interest = ['product', 'app', 'env', 'role']
    red_warning_days = 30
    orange_warning_days = 180
    
    #Configuration for report sending
    report_title = "Reserved Instance Expiry"
    subject_string = "lambda report - %s" % report_title
    from_address = 'lambda_reporting@4a42.org'
    to_address = 'report_recipient@4a42.org'
    
    
    #Headers for full report table
    report_list = [['id', 'AZ', 'Type', 'Count', 'Length (years)', 'Time Left',]+tags_of_interest ]
    red_warning_reservations = []
    orange_warning_reservations = []
            
    for region in regions:
        print "Processing %s" % region
        ec2 = boto3.client('ec2', region_name=region)
        response = ec2.describe_reserved_instances()
        for ri in response['ReservedInstances']:
            time_left = ri[u'End'] - datetime.datetime.now(tzlocal())
            
            if time_left < datetime.timedelta(days=red_warning_days):
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
                print "Looking for ", tag
                row.append(tags.get(tag,'-'))
            
            report_list.append( row )
     
    #Created text version
    msg = "%s\n" % report_title
    msg += "\n".join(["\t".join([str(cell) for cell in row]) for row in report_list])
    
    #Create HTML Version
    html_msg = '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional = //EN"><html> <head><style type="text/css"> H2 { color:#FF0000; } H3 { color:#FFA500; } </style></head><body><h1>Global Reserved Instance Report</h1>'
    
    if len(red_warning_reservations):
        html_msg+="<h2>Warning the following will expire within %s days!</h2>" % red_warning_days
        for row in red_warning_reservations:
            html_msg += "<h2>Warning %s (%s) expires in less than 30 days (%s)</h2>" % (row[0], row[1], row[2])
    if len(orange_warning_reservations):
        html_msg+="<h3>Warning the following will expire within %s days!</h3>" % orange_warning_days
        for row in orange_warning_reservations:
            html_msg += "<h4>Warning %s (%s) expires in less than 30 days (%s)</h4>" % (row[0], row[1], row[2])
            
    html_msg += "<h4>All Reservations</h4>"
    html_msg += list_to_html_table(report_list)
    html_msg += '</body></html>'
    
    ses = boto3.client('ses')
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
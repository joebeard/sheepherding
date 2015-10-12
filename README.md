# sheepherding
## Summary
A collection of scripts designed to be run periodically through on AWS Lambda to manage an AWS deployment. These are simple scipts, written in python, to provide some inspiration on what can be achieved without relying on third party reporting tools or dedicated reporting instances. Many of these scripts cost fractions of cents to run! A script run once a week, taking 60s to execute and using the minimum ammount of ram will cost less than $0.05 a year!
# Current Scripts
* ```reserved_instance_report.py``` - This provides a report of all reserved instances and those that will shortly expire to ensure that cost savings are maintained.
